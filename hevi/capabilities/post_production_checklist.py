"""Post-production checklist gate (``qa.post_production_checklist``).

Clean-room rewrite of the *method* in ``hevi-vs-video-workflow-7steps.md``
step 7 ("what post can do, never hand to the model"): subtitles, title
cards, watermark credits, music replacement, speed changes, assembly,
and freeze-frame padding all belong to the edit stage -- cheap,
exact, repeatable, and free of generation quota. This module is the
checklist that owns them, in two directions:

1. The checklist itself: all seven items must be accounted for
   (``done`` / ``pending`` / ``not_applicable``). A missing item
   fails; a pending item keeps the verdict ``not_checked`` under
   the ``qa.verdict_vocabulary`` rule -- pending post work is not
   finished work.
2. The generation side must not take post work: a generation plan
   whose task list contains a post item, or whose prompt text
   instructs the model to render one, fails. The prompt-text scan
   is a keyword heuristic over explicit generation-side phrases
   ("generate subtitles", "burn subtitles in", ...); a prompt that
   marks a subtitle line as post overlay (the ``[字幕·后期叠加]``
   marker the compiler already emits) passes, because it assigns
   the work to post instead of to the model.

The freeze-frame pad rule: a shot that comes up short may be
padded with a held frame only up to a caller-supplied threshold;
beyond it the shot must be regenerated or escalated. The threshold
is required input -- no number in this module invents one.

This module judges plans only. It performs no edit and no render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

POST_ITEMS = (
    "subtitles",
    "title_card",
    "watermark_credit",
    "music_replace",
    "speed_change",
    "assembly",
    "freeze_frame_pad",
)

ITEM_STATUSES = ("done", "pending", "not_applicable")

# Explicit generation-side phrases: the model is being asked to do
# post work. Each is a whole instruction, not a bare noun, so a
# prompt that merely mentions a subtitle line for post overlay does
# not trip the scan. The post-overlay marker is exempted outright.
_GENERATION_SIDE_PHRASES = (
    "生成字幕", "烧录字幕", "画面加字幕", "生成片名", "生成标题卡",
    "生成水印", "生成配乐", "生成背景音乐", "变速生成", "拼接成片",
    "定格补时长", "generate subtitles", "burn in subtitles",
    "generate title card", "generate watermark", "generate music",
)

_POST_OVERLAY_MARKER = "后期叠加"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_post_checklist(checklist: Any) -> dict[str, Any]:
    """Judge the seven-item post checklist. Returns a report."""
    issues: list[dict[str, Any]] = []
    items: dict[str, str] = {}
    if not isinstance(checklist, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "items": {},
            "issues": [{
                "code": "checklist_not_object",
                "detail": "qa.post_production_checklist: checklist must be "
                         "an object keyed by the seven post items",
            }],
        }
    for name in POST_ITEMS:
        status = checklist.get(name)
        if status is None:
            issues.append({
                "code": f"missing_{name}",
                "detail": f"qa.post_production_checklist: post item "
                         f"'{name}' is not accounted for; all seven items "
                         "must be done, pending, or not_applicable",
            })
            continue
        if status not in ITEM_STATUSES:
            issues.append({
                "code": f"bad_status_{name}",
                "detail": f"qa.post_production_checklist: post item "
                         f"'{name}' status must be one of "
                         f"{', '.join(ITEM_STATUSES)}, not {status!r}",
            })
            continue
        items[name] = status
    extra = sorted(set(checklist) - set(POST_ITEMS))
    if extra:
        issues.append({
            "code": "unknown_post_items",
            "detail": "qa.post_production_checklist: unknown post items "
                     f"{extra}; the checklist is exactly the seven items",
        })
    if issues:
        verdict = "fail"
    elif any(s == "pending" for s in items.values()):
        verdict = "not_checked"
    else:
        verdict = "pass"
    return {"ok": not issues, "verdict": verdict, "items": items,
            "issues": issues}


def check_generation_side(
    generation_tasks: Any = None,
    prompt_text: Any = None,
) -> dict[str, Any]:
    """Refuse generation plans that take on post work. Returns a report."""
    issues: list[dict[str, Any]] = []
    if generation_tasks is not None:
        if not isinstance(generation_tasks, list):
            issues.append({
                "code": "generation_tasks_not_list",
                "detail": "qa.post_production_checklist: generation_tasks "
                         "must be a list",
            })
        else:
            for task in generation_tasks:
                if task in POST_ITEMS:
                    issues.append({
                        "code": "post_item_in_generation",
                        "detail": "qa.post_production_checklist: generation "
                                 f"plan contains post item '{task}'; that "
                                 "work belongs to the edit stage, not to "
                                 "a generation call",
                    })
    if prompt_text is not None:
        if not isinstance(prompt_text, str):
            issues.append({
                "code": "prompt_text_not_string",
                "detail": "qa.post_production_checklist: prompt_text must "
                         "be a string",
            })
        elif _POST_OVERLAY_MARKER not in prompt_text:
            for phrase in _GENERATION_SIDE_PHRASES:
                if phrase in prompt_text:
                    issues.append({
                        "code": "generation_side_phrase",
                        "detail": "qa.post_production_checklist: prompt "
                                 f"instructs the model to do post work "
                                 f"({phrase!r}); move it to the edit stage",
                    })
    return {"ok": not issues,
            "verdict": "pass" if not issues else "fail",
            "issues": issues}


def check_freeze_pad_rule(
    shortfall_s: Any,
    *,
    threshold_s: Any,
) -> dict[str, Any]:
    """Freeze-frame padding rule: pad only up to a caller-supplied threshold.

    ``threshold_s`` is required and must be a positive number; no
    default is invented here. Beyond the threshold the verdict is
    ``fail`` with the escalation named (regenerate or escalate).
    """
    if not _is_number(threshold_s) or float(threshold_s) <= 0:
        raise CapabilityError(
            "qa.post_production_checklist: threshold_s is required and "
            "must be a positive number; the pad threshold is set by "
            "the caller and measured, never defaulted from an article"
        )
    if not _is_number(shortfall_s) or float(shortfall_s) < 0:
        raise CapabilityError(
            "qa.post_production_checklist: shortfall_s must be a "
            "non-negative number of seconds"
        )
    shortfall = float(shortfall_s)
    threshold = float(threshold_s)
    if shortfall <= threshold:
        return {"ok": True, "verdict": "pass", "shortfall_s": shortfall,
                "threshold_s": threshold,
                "action": "pad with a held freeze frame in post"}
    return {"ok": False, "verdict": "fail", "shortfall_s": shortfall,
            "threshold_s": threshold,
            "action": "regenerate the shot or escalate; the shortfall "
                     "exceeds the freeze-pad threshold"}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checklist = check_post_checklist(params.get("checklist"))
    generation = check_generation_side(
        params.get("generation_tasks"), params.get("prompt_text"))
    report = {
        "checklist": checklist,
        "generation_side": generation,
        "verdict": ("fail" if checklist["verdict"] == "fail"
                    or generation["verdict"] == "fail"
                    else checklist["verdict"]),
    }
    if report["verdict"] == "fail":
        details = [i["detail"] for i in checklist["issues"]]
        details += [i["detail"] for i in generation["issues"]]
        raise CapabilityError(
            "qa.post_production_checklist: " + "; ".join(details))
    report_path = out_dir / "post_production_checklist.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_post_production_checklist_capabilities_once() -> list[str]:
    """Register ``qa.post_production_checklist`` on the registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.post_production_checklist",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "checklist": {"type": "object"},
                    "generation_tasks": {"type": "array"},
                    "prompt_text": {"type": "string"},
                },
                "required": ["checklist"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Post-production checklist: the seven post items "
                "(subtitles, title card, watermark credit, music "
                "replacement, speed change, assembly, freeze-frame "
                "pad) must all be accounted for, and no generation "
                "plan may take post work onto itself. Pending post "
                "work keeps the verdict not_checked. Judges plans "
                "only; performs no edit."
            ),
            line="qa",
        )
    )
    return ["qa.post_production_checklist"]


register_post_production_checklist_capabilities_once()
