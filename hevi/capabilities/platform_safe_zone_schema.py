"""Platform safe zone schema (``video.platform_safe_zone_schema``).

Fake-level contract for a platform safe zone of the kind
described in the ChrisHKAI-Video creator-intro review (see
``CHRISHKAI_VIDEO_ATTRIBUTION.md``): one of the six reviewed
platform themes — x-desktop, x-mobile, douyin-mobile,
xhs-mobile, channels-mobile, ig-mobile — with the control
occlusions and safe frame for that platform. The contract
certifies the shape of the plan only. It verifies nothing on
a real device: any plan claiming a safe zone was verified
here fails outright. Every compiled contract declares
``executed_here: false``, and real device verification is a
separate case.
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

# The six reviewed platform themes, closed list.
PLATFORMS: tuple[str, ...] = (
    "x-desktop",
    "x-mobile",
    "douyin-mobile",
    "xhs-mobile",
    "channels-mobile",
    "ig-mobile",
)


def compile_platform_safe_zone(plan: Any) -> dict[str, Any]:
    """Compile one platform safe zone contract.

    ``plan`` carries ``platform`` and ``safe_zone`` (top,
    bottom, left and right margins). Raises
    :class:`CapabilityError` on any shape violation, on an
    unknown platform, on a missing or negative margin, or on
    any claim that the safe zone was verified here. The
    returned contract records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("Platform safe zone plan must be an object")
    if plan.get("executed_here") is True or plan.get("verified_here") is True:
        raise CapabilityError(
            "safe zone verification claims are refused here; this contract executes nothing"
        )
    platform = plan.get("platform")
    if platform not in PLATFORMS:
        raise CapabilityError(
            "Platform safe zone contract covers the six reviewed platform themes only"
        )
    safe_zone = plan.get("safe_zone")
    if not isinstance(safe_zone, dict):
        raise CapabilityError("Platform safe zone plan requires a safe_zone record")
    margins: dict[str, float] = {}
    for edge in ("top", "bottom", "left", "right"):
        value = safe_zone.get(edge)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise CapabilityError(f"safe_zone {edge} margin must be a non-negative number")
        margins[edge] = value
    return {
        "contract": "platform-safe-zone",
        "platform": platform,
        "safe_zone": margins,
        "executed_here": False,
        "verified_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_platform_safe_zone(params.get("plan"))
    report_path = out_dir / "platform_safe_zone_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "platform": report["platform"],
            "executed_here": False,
        },
    )


def register_platform_safe_zone_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.platform_safe_zone_schema",
            kind="video",
            aspects=["16:9", "9:16"],
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
            layer="obase",
            description=(
                "Platform safe zone contract (fake): one of six "
                "reviewed platform themes with control occlusions and "
                "safe frame; no on-device verification."
            ),
        )
    )
    return ["video.platform_safe_zone_schema"]


__all__ = [
    "PLATFORMS",
    "compile_platform_safe_zone",
    "register_platform_safe_zone_schema_capabilities_once",
]
