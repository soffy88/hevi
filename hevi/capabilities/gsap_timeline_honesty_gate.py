"""GSAP timeline honesty gate (``qa.gsap_timeline_honesty_gate``).

One film, one timeline, paused, rendering on update. The
timeline starts paused and re-renders through its onUpdate
callback; a second timeline is a failure. Any element that
carries a CSS transform must be animated with ``fromTo``
and must keep its xPercent/yPercent: mixing a CSS transform
with GSAP position animation on the same element is refused,
because the two writers fight over the same transform and
the frame that ships is neither.

GSAP itself is not vendored here and its licence is not
MIT: the vendored GSAP file carries the GreenSock standard
licence (Copyright GreenSock, all rights reserved). A plan
may only declare ``gsap_source`` as ``method_only`` (hevi's
own timeline method, no GSAP code) or
``vendored_standard_license`` (GSAP shipped under its own
standard licence). Claiming MIT for GSAP fails.

This gate judges timeline declarations only; it never runs
GSAP, never renders a frame, and never copies text or code
from any outside repository. See
``AETHERVIZ_G4_G5_ATTRIBUTION.md``.
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

GSAP_SOURCES: tuple[str, ...] = (
    "method_only",
    "vendored_standard_license",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_gsap_timeline_honesty(plan: Any) -> dict[str, Any]:
    """Validate one GSAP timeline declaration.

    ``plan`` carries ``timeline_count`` (must be 1),
    ``paused`` (must be true), ``on_update_renders`` (must be
    true), ``gsap_source`` (``method_only`` or
    ``vendored_standard_license``), and ``tweens`` (each
    ``{element, css_transform_present, uses_from_to,
    keeps_x_percent, keeps_y_percent, gsap_position_anim}``).
    A CSS-transformed element animated without ``fromTo``, or
    a ``fromTo`` that drops xPercent/yPercent, fails. Returns
    a report; never raises.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(plan, dict):
        return fail("plan_not_object", "plan must be a JSON object")
    if plan.get("timeline_count") != 1:
        return fail(
            "timeline_count_wrong",
            "exactly one GSAP timeline is required",
        )
    if plan.get("paused") is not True:
        return fail(
            "timeline_not_paused",
            "the timeline must start paused",
        )
    if plan.get("on_update_renders") is not True:
        return fail(
            "on_update_missing",
            "the timeline must re-render through its onUpdate callback",
        )
    if plan.get("gsap_source") not in GSAP_SOURCES:
        return fail(
            "gsap_license_mislabelled",
            "gsap_source must be 'method_only' or "
            "'vendored_standard_license': GSAP is GreenSock standard "
            "licence, not MIT",
        )
    tweens = plan.get("tweens")
    if not isinstance(tweens, list):
        return fail(
            "tweens_missing",
            "tweens must be a list (possibly empty)",
        )
    for index, tween in enumerate(tweens):
        if not isinstance(tween, dict):
            return fail(
                "tween_not_object",
                f"tweens[{index}] must be an object",
            )
        element = tween.get("element", f"tweens[{index}]")
        if tween.get("css_transform_present") is True:
            if tween.get("uses_from_to") is not True:
                return fail(
                    "transform_mix",
                    f"element {element!r} carries a CSS transform but "
                    "is not animated with fromTo: CSS and GSAP must "
                    "not both write its position",
                )
            if tween.get("keeps_x_percent") is not True or tween.get("keeps_y_percent") is not True:
                return fail(
                    "percent_lost",
                    f"element {element!r} uses fromTo but drops xPercent/yPercent",
                )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "timeline_count": 1,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_gsap_timeline_honesty(params.get("plan"))
    report_path = out_dir / "gsap_timeline_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_gsap_timeline_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.gsap_timeline_honesty_gate",
            kind="line",
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
            layer="oskill",
            description=(
                "GSAP timeline honesty gate: one timeline, paused, "
                "rendering on update; CSS transforms animated only "
                "with fromTo keeping xPercent/yPercent; GSAP is "
                "GreenSock standard licence, never MIT."
            ),
        )
    )
    return ["qa.gsap_timeline_honesty_gate"]


__all__ = [
    "GSAP_SOURCES",
    "check_gsap_timeline_honesty",
    "register_gsap_timeline_honesty_gate_capabilities_once",
]
