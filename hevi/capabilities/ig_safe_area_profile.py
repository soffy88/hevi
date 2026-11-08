"""Instagram 9:16 safe-area profile gate (``qa.ig_safe_area_profile``).

Discipline gate only. A 9:16 vertical plan that claims Instagram
safe-area compliance must use the dedicated IG profile, not the
generic 48px margin from ``hevi.validation.layout_gate`` and not
the karaoke vertical margins (side 80 / top 140 / bottom 220).
The IG profile, restated in hevi's own words from the method
notes, is: canvas 1080x1920, keep-out top 220px, keep-out bottom
to y=1500 (420px), keep-out sides 100px. Every named element
(caption, face, prop, label) must sit fully inside the profile
box. A plan that names the generic margin as its profile fails.
This gate judges the plan only and renders nothing. See
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

# Dedicated IG 9:16 profile, in hevi's own restatement. These
# numbers describe the platform overlay keep-out, not a hevi
# invention: top strip, bottom strip, and side strips are
# covered by interface chrome on the target surface.
PROFILE_NAME = "ig_safe_9x16"
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
SAFE_TOP = 220
SAFE_BOTTOM = 1500
SAFE_SIDE = 100


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def ig_safe_box() -> dict[str, int]:
    """Return the profile box as [left, top, right, bottom]."""
    return {
        "left": SAFE_SIDE,
        "top": SAFE_TOP,
        "right": CANVAS_WIDTH - SAFE_SIDE,
        "bottom": SAFE_BOTTOM,
    }


def check_ig_safe_area(plan: Any) -> dict[str, Any]:
    """Check a vertical plan against the IG 9:16 safe-area profile.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    ``issues``, and per-element results. A non-object plan, a
    canvas other than 1080x1920, a missing or wrong profile
    declaration, or any element outside the profile box fails.
    """
    issues: list[dict[str, str]] = []
    elements_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
            "elements": elements_out,
            "profile": PROFILE_NAME,
        }
    canvas = plan.get("canvas")
    if not isinstance(canvas, dict):
        issues.append(
            _issue("canvas_missing", "plan must declare a canvas object")
        )
    else:
        width = canvas.get("width")
        height = canvas.get("height")
        if width != CANVAS_WIDTH or height != CANVAS_HEIGHT:
            issues.append(
                _issue(
                    "canvas_not_1080x1920",
                    "the IG profile is defined only for a "
                    "1080x1920 canvas",
                )
            )
    profile = plan.get("profile")
    if profile is None:
        issues.append(
            _issue(
                "profile_undeclared",
                "plan must declare profile 'ig_safe_9x16'; the "
                "generic 48px margin is not this profile",
            )
        )
    elif profile != PROFILE_NAME:
        issues.append(
            _issue(
                "profile_wrong",
                f"profile must be {PROFILE_NAME!r}, not {profile!r}",
            )
        )
    elements = plan.get("elements")
    if not isinstance(elements, list) or not elements:
        issues.append(
            _issue("elements_missing", "plan must declare a non-empty elements list")
        )
        elements = elements if isinstance(elements, list) else []
    box = ig_safe_box()
    for index, element in enumerate(elements):
        label = f"elements[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(element, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each element must be an object")
            )
            elements_out.append(entry)
            continue
        entry["kind"] = element.get("kind")
        element_box = element.get("box")
        if (
            not isinstance(element_box, list)
            or len(element_box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in element_box)
        ):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:box_missing",
                    "each element must declare box [left, top, right, bottom]",
                )
            )
        else:
            left, top, right, bottom = element_box
            if (
                left < box["left"]
                or top < box["top"]
                or right > box["right"]
                or bottom > box["bottom"]
            ):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:outside_profile",
                        "element box must sit fully inside the IG "
                        "safe-area profile box",
                    )
                )
        if entry["issues"]:
            entry["ok"] = False
        elements_out.append(entry)
        issues.extend(entry["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "elements": elements_out,
        "profile": PROFILE_NAME,
        "profile_box": box,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_ig_safe_area(params.get("plan"))
    report_path = out_dir / "ig_safe_area_profile.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_ig_safe_area_profile_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.ig_safe_area_profile",
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
                "IG 9:16 safe-area profile gate: a vertical plan "
                "must declare the dedicated 220/1500/100 profile "
                "on a 1080x1920 canvas and keep every element "
                "inside it; the generic 48px margin never passes "
                "as this profile."
            ),
        )
    )
    return ["qa.ig_safe_area_profile"]


__all__ = [
    "check_ig_safe_area",
    "ig_safe_box",
    "register_ig_safe_area_profile_capabilities_once",
]
