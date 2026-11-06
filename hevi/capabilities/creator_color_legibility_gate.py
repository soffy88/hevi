"""Creator color legibility gate (``qa.creator_color_legibility_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): color is
checked for readability, not taste. Text must reach a 3:1
contrast ratio, large toy areas 1.6:1, and the palette must
be taken from the creator's own pictures. A palette table is
required, and the picture must survive a black-and-white
check — person and background still separable — or the
regrade must be recorded. This gate judges the color record
only. It renders nothing: ``executed_here`` is always false.
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

# Readability floors, restated from the reviewed method.
MIN_TEXT_CONTRAST = 3.0
MIN_TOY_AREA_CONTRAST = 1.6


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_creator_color_legibility(color: Any) -> dict[str, Any]:
    """Validate a creator-intro color record.

    Pass requires text contrast of at least 3:1, large toy
    area contrast of at least 1.6:1, a palette taken from the
    creator's own pictures, a palette table, and a passed
    black-and-white check — or a recorded regrade when the
    check fails.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(color, dict):
        return fail("color_not_object", "color must be a JSON object")
    text = color.get("text_contrast")
    if not isinstance(text, (int, float)) or isinstance(text, bool):
        return fail(
            "text_contrast_unmeasured",
            "color must state the text contrast ratio",
        )
    if text < MIN_TEXT_CONTRAST:
        return fail(
            "text_contrast_low",
            f"text contrast {text}:1 is below the 3:1 floor",
        )
    toy_area = color.get("toy_area_contrast")
    if not isinstance(toy_area, (int, float)) or isinstance(toy_area, bool):
        return fail(
            "toy_area_contrast_unmeasured",
            "color must state the large toy area contrast ratio",
        )
    if toy_area < MIN_TOY_AREA_CONTRAST:
        return fail(
            "toy_contrast_low",
            f"large toy area contrast {toy_area}:1 is below the 1.6:1 floor",
        )
    if color.get("palette_from_own_images") is not True:
        return fail(
            "palette_not_from_own_images",
            "the palette must be taken from the creator's own pictures",
        )
    if not isinstance(color.get("palette_table"), dict) or not color["palette_table"]:
        return fail(
            "palette_missing",
            "color must carry a palette table",
        )
    if color.get("bw_check_passed") is not True and not color.get("regrade_recorded"):
        return fail(
            "bw_check_failed",
            "black-and-white check failed and no regrade is recorded; person and background must stay separable",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_creator_color_legibility(params.get("color"))
    report_path = out_dir / "creator_color_legibility_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_creator_color_legibility_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.creator_color_legibility_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "color": {"type": "object"},
                },
                "required": ["color"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Creator color legibility gate: text contrast at "
                "least 3:1, large toy area at least 1.6:1, palette "
                "from the creator's own pictures, palette table, "
                "black-and-white check or recorded regrade."
            ),
        )
    )
    return ["qa.creator_color_legibility_gate"]


__all__ = [
    "MIN_TEXT_CONTRAST",
    "MIN_TOY_AREA_CONTRAST",
    "check_creator_color_legibility",
    "register_creator_color_legibility_gate_capabilities_once",
]
