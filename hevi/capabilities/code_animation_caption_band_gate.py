"""Code-animation caption band gate (``qa.code_animation_caption_band_gate``).

Discipline gate only. A code-animated vertical plan must
keep its caption band inside the IG 9:16 safe-area profile
(top 220, bottom 1500, sides 100 on a 1080x1920 canvas),
must keep faces and key props clear of the caption band,
and must declare word-level timing alignment. When the
narration changes, the plan must declare that timing was
re-done; a changed narration on stale timing fails. This
gate judges the plan only and renders nothing. It does not
replace the generic safe-area check or the karaoke margins;
it adds the caption-band rule for code-animated pieces. See
ANIMATION_SKILLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
SAFE_TOP = 220
SAFE_BOTTOM = 1500
SAFE_SIDE = 100
# Kinds that must never sit on top of the caption band.
CLEAR_KINDS = ("face", "prop")


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _overlaps(a: list, b: list) -> bool:
    return not (
        a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3]
    )


def check_caption_band(plan: Any) -> dict[str, Any]:
    """Check a code-animation plan's caption band discipline.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. A band outside the safe area, a face or
    prop overlapping the band, unaligned word timing, or a
    narration change without re-timing all fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    canvas = plan.get("canvas")
    if not isinstance(canvas, dict):
        issues.append(
            _issue("canvas_missing", "plan must declare a canvas object")
        )
    elif canvas.get("width") != CANVAS_WIDTH or canvas.get("height") != CANVAS_HEIGHT:
        issues.append(
            _issue(
                "canvas_not_1080x1920",
                "the caption-band profile is defined only for "
                "a 1080x1920 canvas",
            )
        )
    band = plan.get("caption_band")
    band_box: list | None = None
    if not isinstance(band, dict):
        issues.append(
            _issue("caption_band_missing", "plan must declare a caption_band")
        )
    else:
        band_box = band.get("box")
        if (
            not isinstance(band_box, list)
            or len(band_box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in band_box)
        ):
            issues.append(
                _issue(
                    "caption_band_box_missing",
                    "caption_band must declare box "
                    "[left, top, right, bottom]",
                )
            )
            band_box = None
        else:
            left, top, right, bottom = band_box
            if (
                left < SAFE_SIDE
                or top < SAFE_TOP
                or right > CANVAS_WIDTH - SAFE_SIDE
                or bottom > SAFE_BOTTOM
            ):
                issues.append(
                    _issue(
                        "caption_band_outside_safe_area",
                        "the caption band must sit inside the IG "
                        "safe-area profile",
                    )
                )
    elements = plan.get("elements")
    if not isinstance(elements, list):
        issues.append(
            _issue("elements_missing", "plan must declare an elements list")
        )
        elements = []
    if band_box is not None:
        for index, element in enumerate(elements):
            label = f"elements[{index}]"
            if not isinstance(element, dict):
                issues.append(
                    _issue(f"{label}:not_object", "each element must be an object")
                )
                continue
            if element.get("kind") not in CLEAR_KINDS:
                continue
            element_box = element.get("box")
            if (
                isinstance(element_box, list)
                and len(element_box) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in element_box)
                and _overlaps(element_box, band_box)
            ):
                issues.append(
                    _issue(
                        f"{label}:overlaps_caption_band",
                        "faces and key props must stay clear of "
                        "the caption band",
                    )
                )
    if plan.get("word_timing_aligned") is not True:
        issues.append(
            _issue(
                "word_timing_unaligned",
                "plan must declare word-level timing alignment",
            )
        )
    if (
        plan.get("narration_changed") is True
        and plan.get("retimed_on_narration_change") is not True
    ):
        issues.append(
            _issue(
                "narration_changed_without_retiming",
                "a changed narration requires re-done timing",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_caption_band(params.get("plan"))
    report_path = out_dir / "code_animation_caption_band.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_code_animation_caption_band_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.code_animation_caption_band_gate",
            kind="line",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Code-animation caption band gate: the caption "
                "band stays inside the IG safe-area profile, "
                "faces and key props stay clear of it, word "
                "timing is declared aligned, and a changed "
                "narration requires re-timing."
            ),
        )
    )
    return ["qa.code_animation_caption_band_gate"]


__all__ = [
    "check_caption_band",
    "register_code_animation_caption_band_gate_capabilities_once",
]
