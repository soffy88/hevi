"""Hook-reversal three-act script gate (``qa.hook_reversal_script_gate``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 4: a short
explainer script opens with a counter-intuitive hook, tells the chain
of events, and closes with one reversal sentence. In hevi's caliber
the structure is a judged plan, never a generated script:

1. The script must declare exactly three acts in order: ``hook``,
   ``chain``, ``reversal``. Each act carries non-empty text and a
   positive duration in seconds.
2. Act durations must tile the declared total duration (when one is
   declared) within a 1ms rounding tolerance.
3. The reversal must be a different sentence from the hook and must
   be the last act; a script that ends on the chain fails.
4. Factual topics must declare their sources. A script whose
   ``topic_kind`` is ``factual`` without a non-empty ``sources``
   list fails; the gate judges the declaration, it never verifies
   the facts themselves.

This module judges plans only. It writes no scripts, copies no
tutorial text, and treats no anecdote as measured evidence.
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

_EPS = 0.001
_ACTS = ("hook", "chain", "reversal")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_hook_reversal_script(script: Any) -> dict[str, Any]:
    """Judge one hook-reversal script plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    acts_out: list[dict[str, Any]] = []
    if not isinstance(script, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("script_not_object", "script must be an object")],
            "acts": [],
        }
    acts = script.get("acts")
    if not isinstance(acts, dict):
        issues.append(_issue("acts_missing", "script must declare an 'acts' object"))
        acts = {}
    total = 0.0
    for name in _ACTS:
        act = acts.get(name)
        if not isinstance(act, dict):
            issues.append(_issue("act_missing", f"act '{name}' is missing"))
            continue
        if not _is_nonempty_str(act.get("text")):
            issues.append(_issue("act_text_missing", f"act '{name}' must carry text"))
        duration = act.get("duration_s")
        if not _is_number(duration) or float(duration) <= 0:
            issues.append(
                _issue("act_duration_invalid", f"act '{name}' duration_s must be > 0")
            )
            duration = 0.0
        total += float(duration)
        acts_out.append({"act": name, "duration_s": float(duration)})
    order = [key for key in acts if key in _ACTS]
    if order != [name for name in _ACTS if name in acts]:
        issues.append(
            _issue("act_order_wrong", "acts must appear in hook, chain, reversal order")
        )
    hook_text = acts.get("hook", {}).get("text") if isinstance(acts.get("hook"), dict) else None
    reversal_text = (
        acts.get("reversal", {}).get("text")
        if isinstance(acts.get("reversal"), dict)
        else None
    )
    if (
        _is_nonempty_str(hook_text)
        and _is_nonempty_str(reversal_text)
        and str(hook_text).strip() == str(reversal_text).strip()
    ):
        issues.append(
            _issue(
                "reversal_same_as_hook",
                "the reversal sentence must differ from the hook sentence",
            )
        )
    declared_total = script.get("total_duration_s")
    if declared_total is not None:
        if not _is_number(declared_total) or float(declared_total) <= 0:
            issues.append(
                _issue("total_duration_invalid", "total_duration_s must be > 0")
            )
        elif abs(total - float(declared_total)) > _EPS:
            issues.append(
                _issue(
                    "acts_do_not_tile_total",
                    f"acts sum to {total}, declared total is {declared_total}",
                )
            )
    if script.get("topic_kind") == "factual":
        sources = script.get("sources")
        if not isinstance(sources, list) or not any(
            _is_nonempty_str(item) for item in sources
        ):
            issues.append(
                _issue(
                    "factual_sources_missing",
                    "factual topics must declare at least one source",
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "acts": acts_out,
        "total_duration_s": total,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_hook_reversal_script(params.get("script"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "hook_reversal_script_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_hook_reversal_script_gate_capabilities_once() -> list[str]:
    """Register ``qa.hook_reversal_script_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.hook_reversal_script_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "script": {"type": "object"},
                },
                "required": ["script"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Hook-reversal script gate: hook, chain and reversal acts "
                "in order, each timed, durations tiling the total, and "
                "factual topics declaring sources. Plans are judged, "
                "never written."
            ),
            line="qa",
        )
    )
    return ["qa.hook_reversal_script_gate"]


register_hook_reversal_script_gate_capabilities_once()
