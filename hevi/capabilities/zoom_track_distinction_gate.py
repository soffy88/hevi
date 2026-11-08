"""Zoom/track distinction gate (``qa.zoom_track_distinction_gate``).

Clean-room discipline gate only. A zoom and a dolly/track move are
different physics and must never be described as each other:

* zoom family (slow/fast/crash zoom in/out): the lens focal length
  changes; the camera body does not travel. A claim describing the
  body as moving fails.
* body family (dolly, truck, pedestal, slider, push past, arc,
  orbit, all tracking forms, crane, drone, helicopter, pass
  through): the camera body physically travels; the focal length
  does not change. A claim describing a focal-length change fails.

Rotation, handheld, body-mounted, first-person, optical
(tilt-shift) and composite/time effects (infinite zoom, earth zoom
out, time-lapse) are outside this binary check and pass with
mechanism ``other``; the composite/time three are checked by the
special-movement flag gate instead. This gate judges the claim
only and renders nothing. No site prompt text is copied here. See
CAMERA_MOVEMENTS_ATTRIBUTION.md.
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

ZOOM_IDS: frozenset[str] = frozenset(
    {
        "slow_zoom_in",
        "slow_zoom_out",
        "fast_zoom_in",
        "fast_zoom_out",
        "crash_zoom_in",
        "crash_zoom_out",
    }
)

BODY_IDS: frozenset[str] = frozenset(
    {
        "dolly_in",
        "dolly_out",
        "truck_right",
        "truck_left",
        "pedestal_up",
        "pedestal_down",
        "slider_right",
        "slider_left",
        "push_past",
        "arc_right",
        "arc_left",
        "orbit_clockwise",
        "orbit_counterclockwise",
        "tracking_shot",
        "follow_shot",
        "reverse_tracking",
        "side_tracking",
        "low_tracking",
        "vehicle_tracking",
        "chase_shot",
        "crane_up",
        "crane_down",
        "drone_push_in",
        "drone_pull_back",
        "helicopter_shot",
        "pass_through_objects",
    }
)

# Word stems (lowercased) naming each mechanism, English and Chinese.
_FOCAL_STEMS = ("focal", "zoom", "scale", "焦距", "变焦", "缩放")
_BODY_STEMS = (
    "physicall",
    "mov",
    "travel",
    "fly",
    "circl",
    "slid",
    "rais",
    "lower",
    "follow",
    "push",
    "机身",
    "移动",
    "前推",
    "后拉",
    "环绕",
    "跟随",
    "飞行",
)


def classify_mechanism(movement_id: str) -> str:
    """Return ``zoom``, ``body`` or ``other`` for a movement id."""
    if movement_id in ZOOM_IDS:
        return "zoom"
    if movement_id in BODY_IDS:
        return "body"
    return "other"


def _mentions(text: str, stems: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(stem in lowered for stem in stems)


def check_zoom_track_distinction(claim: Any) -> dict[str, Any]:
    """Validate one mechanism claim. Returns a report; never raises.

    A claim is ``{"movement_id": ..., "mechanism_text": ...}``
    (``"movement"`` is accepted as the text key). Unknown movement
    ids fail; ``other``-family movements pass with a note.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(claim, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                {
                    "code": "claim_not_object",
                    "detail": "each mechanism claim must be an object",
                }
            ],
            "movement_id": None,
            "mechanism": None,
        }
    movement_id = claim.get("movement_id")
    text = str(claim.get("mechanism_text", claim.get("movement", "")))
    mechanism = None
    if not isinstance(movement_id, str) or not movement_id:
        issues.append(
            {"code": "movement_id_missing", "detail": "claim names no movement"}
        )
    elif movement_id not in ZOOM_IDS and movement_id not in BODY_IDS:
        from hevi.capabilities.cinematic_techniques import load_movements

        known = {r["id"] for r in load_movements()}
        if movement_id not in known:
            issues.append(
                {
                    "code": f"unknown_movement_id:{movement_id}",
                    "detail": f"{movement_id!r} is not in the movement vocabulary",
                }
            )
        else:
            mechanism = "other"
    else:
        mechanism = classify_mechanism(movement_id)
        if mechanism == "zoom":
            if _mentions(text, _BODY_STEMS):
                issues.append(
                    {
                        "code": "zoom_described_as_body_movement",
                        "detail": (
                            f"{movement_id!r} is a focal-length change; "
                            "the claim describes the camera body travelling"
                        ),
                    }
                )
            elif not _mentions(text, _FOCAL_STEMS):
                issues.append(
                    {
                        "code": "zoom_mechanism_unstated",
                        "detail": (
                            f"{movement_id!r} claim states no focal-length "
                            "or scale change"
                        ),
                    }
                )
        elif mechanism == "body":
            if _mentions(text, _FOCAL_STEMS):
                issues.append(
                    {
                        "code": "body_described_as_zoom",
                        "detail": (
                            f"{movement_id!r} is a physical body move; "
                            "the claim describes a focal-length change"
                        ),
                    }
                )
            elif not _mentions(text, _BODY_STEMS):
                issues.append(
                    {
                        "code": "body_mechanism_unstated",
                        "detail": (
                            f"{movement_id!r} claim states no physical "
                            "body displacement"
                        ),
                    }
                )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "movement_id": movement_id,
        "mechanism": mechanism,
    }


def check_zoom_track_claims(claims: list[Any]) -> dict[str, Any]:
    """Validate a list of mechanism claims."""
    issues: list[dict[str, Any]] = []
    for claim in claims:
        issues.extend(check_zoom_track_distinction(claim)["issues"])
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "checked": len(claims),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    claims = params.get("claims")
    if isinstance(claims, list):
        report: dict[str, Any] = check_zoom_track_claims(claims)
    else:
        report = check_zoom_track_distinction(params.get("claim"))
    report_path = out_dir / "zoom_track_distinction.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_zoom_track_distinction_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.zoom_track_distinction_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                    "claims": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Zoom/track distinction gate: zoom claims must name "
                "a focal-length change and no body travel; body-move "
                "claims must name physical displacement and no "
                "focal-length change; either confusion fails."
            ),
        )
    )
    return ["qa.zoom_track_distinction_gate"]


__all__ = [
    "ZOOM_IDS",
    "BODY_IDS",
    "classify_mechanism",
    "check_zoom_track_distinction",
    "check_zoom_track_claims",
    "register_zoom_track_distinction_gate_capabilities_once",
]
