"""Creator pacing gate (``qa.creator_pacing_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): the pace of
a creator intro is checked against four numbers. Silence
longer than two bars fails. A toy smaller than 8% of the
frame height fails. No landing point inside the first three
seconds fails. A subtitle that stays up for less than its
readable time fails. This gate judges the pacing record
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

# Fail thresholds, restated from the reviewed method.
MAX_SILENCE_BARS = 2.0
MIN_TOY_HEIGHT_FRACTION = 0.08
FIRST_HOOK_LIMIT_S = 3.0


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_creator_pacing(pacing: Any) -> dict[str, Any]:
    """Validate a creator-intro pacing record.

    Pass requires silence of at most two bars, the toy at
    least 8% of frame height, a landing point inside the
    first three seconds, and every subtitle shown for at
    least its readable time.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(pacing, dict):
        return fail("pacing_not_object", "pacing must be a JSON object")
    silence = pacing.get("max_silence_bars")
    if not isinstance(silence, (int, float)) or isinstance(silence, bool):
        return fail(
            "silence_unmeasured",
            "pacing must state the longest silence in bars",
        )
    if silence > MAX_SILENCE_BARS:
        return fail(
            "silence_too_long",
            f"silence of {silence} bars is longer than the two-bar limit",
        )
    toy_height = pacing.get("toy_height_fraction")
    if not isinstance(toy_height, (int, float)) or isinstance(toy_height, bool):
        return fail(
            "toy_height_unmeasured",
            "pacing must state the toy height as a fraction of frame height",
        )
    if toy_height < MIN_TOY_HEIGHT_FRACTION:
        return fail(
            "toy_too_small",
            f"toy is {toy_height} of frame height, below the 8% floor",
        )
    hook = pacing.get("first_hook_second")
    if not isinstance(hook, (int, float)) or isinstance(hook, bool):
        return fail(
            "first_hook_unmeasured",
            "pacing must state the second of the first landing point",
        )
    if hook > FIRST_HOOK_LIMIT_S:
        return fail(
            "no_early_hook",
            f"first landing point is at {hook}s, outside the first three seconds",
        )
    subtitles = pacing.get("subtitles")
    if not isinstance(subtitles, list):
        return fail(
            "subtitles_missing",
            "pacing must list subtitles with their shown and readable times",
        )
    for index, subtitle in enumerate(subtitles):
        if not isinstance(subtitle, dict):
            return fail(
                "subtitle_not_object",
                f"subtitle {index} must be a JSON object",
            )
        shown = subtitle.get("duration_s")
        readable = subtitle.get("min_readable_s")
        if not isinstance(shown, (int, float)) or not isinstance(readable, (int, float)):
            return fail(
                "subtitle_time_unmeasured",
                f"subtitle {index} must state its shown time and its readable time",
            )
        if shown < readable:
            return fail(
                "subtitle_too_short",
                f"subtitle {index} is shown {shown}s, shorter than its readable time {readable}s",
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
    report = check_creator_pacing(params.get("pacing"))
    report_path = out_dir / "creator_pacing_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_creator_pacing_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.creator_pacing_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "pacing": {"type": "object"},
                },
                "required": ["pacing"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Creator pacing gate: silence at most two bars, toy "
                "at least 8% of frame height, a landing point inside "
                "the first three seconds, every subtitle shown for at "
                "least its readable time."
            ),
        )
    )
    return ["qa.creator_pacing_gate"]


__all__ = [
    "FIRST_HOOK_LIMIT_S",
    "MAX_SILENCE_BARS",
    "MIN_TOY_HEIGHT_FRACTION",
    "check_creator_pacing",
    "register_creator_pacing_gate_capabilities_once",
]
