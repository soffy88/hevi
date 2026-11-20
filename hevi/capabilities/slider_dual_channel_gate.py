"""Slider dual-channel sync gate (``qa.slider_dual_channel_gate``).

One slider, one fact, two channels. A single slider update
must change the 3D object property and the SVG path in the
same frame and to the same value. The slider is the single
source of truth: neither channel may carry its own value,
and neither channel may lag a frame behind the other. A
stale channel, a missing channel, or two update paths that
disagree is a failure, not a partial success.

This gate judges update declarations only; it never moves a
slider, never mutates a scene, and never copies text or code
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

CHANNELS: tuple[str, ...] = ("object3d", "svg")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_slider_dual_channel(plan: Any) -> dict[str, Any]:
    """Validate one slider update across both channels.

    ``plan`` carries ``slider_value`` (number),
    ``source_of_truth`` (must be ``"slider"``), and ``updates``
    (a list with exactly one entry per channel: ``object3d``
    and ``svg``; each entry carries ``value`` and ``frame``).
    Both values must equal the slider value; both frames must
    be equal, so neither channel lags. Returns a report; never
    raises.
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
    slider_value = plan.get("slider_value")
    if not _is_number(slider_value):
        return fail(
            "slider_value_undefined",
            "slider_value must be a number",
        )
    if plan.get("source_of_truth") != "slider":
        return fail(
            "source_not_single",
            "source_of_truth must be 'slider': one slider is the "
            "single source of truth for both channels",
        )
    updates = plan.get("updates")
    if not isinstance(updates, list):
        return fail(
            "updates_missing",
            "updates must be a list with one entry per channel",
        )
    by_channel: dict[str, dict[str, Any]] = {}
    for update in updates:
        if not isinstance(update, dict):
            return fail(
                "update_not_object",
                "each update must be an object",
            )
        channel = update.get("channel")
        if channel not in CHANNELS:
            return fail(
                "channel_unknown",
                f"channel must be one of {list(CHANNELS)}",
            )
        if channel in by_channel:
            return fail(
                "channel_duplicate",
                f"channel {channel!r} is updated twice in one slider update",
            )
        by_channel[channel] = update
    for channel in CHANNELS:
        if channel not in by_channel:
            return fail(
                "channel_missing",
                f"channel {channel!r} was not updated by this slider update",
            )
    for channel in CHANNELS:
        value = by_channel[channel].get("value")
        if not _is_number(value) or abs(value - slider_value) > 1e-9:
            return fail(
                "channel_value_mismatch",
                f"channel {channel!r} carries value {value!r}, not the "
                f"slider value {slider_value!r}",
            )
    frames = {channel: by_channel[channel].get("frame") for channel in CHANNELS}
    if any(not isinstance(f, int) or isinstance(f, bool) for f in frames.values()):
        return fail(
            "frame_undeclared",
            "each update must carry an integer frame index",
        )
    if len(set(frames.values())) != 1:
        return fail(
            "channel_lag",
            f"channels updated on different frames {frames}: one channel lags behind the other",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
        "channels": list(CHANNELS),
        "frame": frames["object3d"],
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_slider_dual_channel(params.get("plan"))
    report_path = out_dir / "slider_dual_channel_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_slider_dual_channel_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.slider_dual_channel_gate",
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
                "slider dual-channel sync gate: one slider is the "
                "single source of truth; one update must change the "
                "3D object property and the SVG path to the same "
                "value in the same frame."
            ),
        )
    )
    return ["qa.slider_dual_channel_gate"]


__all__ = [
    "CHANNELS",
    "check_slider_dual_channel",
    "register_slider_dual_channel_gate_capabilities_once",
]
