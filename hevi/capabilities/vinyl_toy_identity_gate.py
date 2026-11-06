"""Vinyl toy identity gate (``qa.vinyl_toy_identity_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): the lead is
a 3D vinyl toy made from the creator's own avatar. The avatar
must be confirmed by its owner and is never redrawn; the toy
body follows the source picture (a lemon has no arms, because
the source has none); fixed features are written down with
their positions so they cannot drift. Only one toy shares the
screen, and the toy and the flat sticker never appear
together. This gate judges the identity record only. It
builds no model and holds no image asset: ``executed_here``
is always false.
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


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_vinyl_toy_identity(toy: Any) -> dict[str, Any]:
    """Validate a vinyl toy identity record.

    Pass requires a user-confirmed avatar that was not
    redrawn, a body that follows the source picture, exactly
    one toy on screen, no flat sticker sharing the screen
    with the toy, and every fixed feature written with its
    position.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(toy, dict):
        return fail("toy_not_object", "toy must be a JSON object")
    if toy.get("avatar_confirmed") is not True:
        return fail(
            "avatar_not_confirmed",
            "the avatar must be confirmed by its owner before the toy is built",
        )
    if toy.get("redraw_avatar") is True:
        return fail(
            "avatar_redrawn",
            "the avatar is never redrawn; the toy follows the confirmed avatar",
        )
    if toy.get("body_follows_source") is not True:
        return fail(
            "body_not_source",
            "the toy body must follow the source picture (a lemon has no arms)",
        )
    if toy.get("on_screen_toys") != 1:
        return fail(
            "toy_count_wrong",
            "exactly one toy shares the screen",
        )
    if toy.get("flat_sticker_present") is True:
        return fail(
            "sticker_and_toy_together",
            "the toy and the flat sticker never appear together",
        )
    features = toy.get("fixed_features")
    if not isinstance(features, dict) or not features:
        return fail(
            "fixed_features_missing",
            "fixed features must be written down, each with its position",
        )
    for name, feature in features.items():
        if not isinstance(feature, dict) or not feature.get("position"):
            return fail(
                "feature_missing_position",
                f"fixed feature {name} is written without its position",
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
    report = check_vinyl_toy_identity(params.get("toy"))
    report_path = out_dir / "vinyl_toy_identity_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_vinyl_toy_identity_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.vinyl_toy_identity_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "toy": {"type": "object"},
                },
                "required": ["toy"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Vinyl toy identity gate: owner-confirmed avatar, "
                "never redrawn, body follows the source picture, one "
                "toy on screen, no flat sticker beside the toy, fixed "
                "features written with positions."
            ),
        )
    )
    return ["qa.vinyl_toy_identity_gate"]


__all__ = [
    "check_vinyl_toy_identity",
    "register_vinyl_toy_identity_gate_capabilities_once",
]
