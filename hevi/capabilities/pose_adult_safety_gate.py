"""Adult-content safety gate (``qa.pose_adult_safety_gate``).

A real gate, not a hint. The existing ``image.pose_library``
only attaches advisory risk hints (low / medium / high) and
never bans a pose; the caller decides. This gate is the
enforcement layer the library was missing: SFW mode is on by
default, sexy and two-person content requires an explicit
adult unlock, and minors are hard-blocked from adult tiers.
Adult content never enters the kids line, whatever the
audience label says.

Verified 18+ inventory (2026-11-20 check): pose sexy system
399 records, two-person system 275 records; costume
sexy/underwear 339 sets. Tiers here are ``standard``,
``sexy``, and ``couple``; costume lingerie, sexy, and
swimwear categories map to the ``sexy`` tier.
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

TIERS: frozenset[str] = frozenset({"standard", "sexy", "couple"})
ADULT_TIERS: frozenset[str] = frozenset({"sexy", "couple"})
KIDS_AUDIENCES: frozenset[str] = frozenset({"kids", "minors", "children"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_pose_adult_safety(decl: Any) -> dict[str, Any]:
    """Validate one adult-content safety declaration.

    Verdicts are ``pass`` / ``fail`` only, and a fail here is
    a hard block, not a hint. A declaration fails when SFW
    mode is off, the tier is unknown, an adult tier is used
    without an age-verified adult and an explicit unlock, or
    adult content is aimed at a kids audience.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(decl, dict):
        return fail("safety_not_object", "safety declaration must be a JSON object")
    if decl.get("sfw_mode") is not True:
        return fail(
            "sfw_mode_off",
            "SFW mode is on by default and must be explicitly true; turning it off is refused",
        )
    tier = decl.get("content_tier")
    if tier not in TIERS:
        return fail(
            "unknown_tier",
            f"content_tier must be one of {sorted(TIERS)}, got {tier!r}",
        )
    audience = decl.get("target_audience")
    if tier in ADULT_TIERS:
        if decl.get("age_verified_adult") is not True:
            return fail(
                "minor_blocked",
                f"tier {tier!r} is adult content; use by anyone who "
                "is not an age-verified adult is hard-blocked",
            )
        if decl.get("explicit_unlock") is not True:
            return fail(
                "explicit_unlock_missing",
                f"tier {tier!r} requires an explicit adult unlock; "
                "silent or default access is refused",
            )
        if audience in KIDS_AUDIENCES:
            return fail(
                "adult_content_to_kids_refused",
                "adult content never enters the kids line, whatever the audience label says",
            )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "content_tier": tier,
        "target_audience": audience,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_adult_safety(params.get("safety"))
    report_path = out_dir / "pose_adult_safety_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_adult_safety_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_adult_safety_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "safety": {"type": "object"},
                },
                "required": ["safety"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery adult-content safety gate: SFW mode on "
                "by default, sexy and couple tiers need an "
                "age-verified adult plus an explicit unlock, minors "
                "hard-blocked, adult content never enters the kids line."
            ),
        )
    )
    return ["qa.pose_adult_safety_gate"]


__all__ = [
    "ADULT_TIERS",
    "KIDS_AUDIENCES",
    "TIERS",
    "check_pose_adult_safety",
    "register_pose_adult_safety_gate_capabilities_once",
]
