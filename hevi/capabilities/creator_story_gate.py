"""Creator story gate (``qa.creator_story_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): story-first.
The person comes before the event — who the creator is, why
they make things, and who they make them for — and only then
the story. Three directions (A/B/C) are drafted, each with a
hook and a payoff, and one of them is recommended. Every
number states its source and when it was read, and historical
milestones keep their original value and date. A turning
point that was invented rather than found fails. This gate
judges the story record only. It generates no video and
spends nothing: ``executed_here`` is always false.
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

DIRECTION_AXES: tuple[str, ...] = ("hook", "payoff")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_creator_story(story: Any) -> dict[str, Any]:
    """Validate a creator-intro story record.

    Pass requires the person to be fixed first, exactly
    three directions each carrying a hook and a payoff with
    exactly one recommended, every number carrying a source
    and a read time, and no invented turning point.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(story, dict):
        return fail("story_not_object", "story must be a JSON object")
    person = story.get("person")
    if not isinstance(person, dict):
        return fail(
            "person_missing",
            "story-first: fix the person (who, why, for whom) before the event",
        )
    for field in ("who", "why", "for_whom"):
        if not person.get(field):
            return fail(
                "person_incomplete",
                f"person is missing {field}; the person comes before the event",
            )
    directions = story.get("directions")
    if not isinstance(directions, list) or len(directions) != 3:
        return fail(
            "directions_not_three",
            "exactly three directions (A/B/C) must be drafted",
        )
    recommended = 0
    for index, direction in enumerate(directions):
        if not isinstance(direction, dict):
            return fail(
                "direction_not_object",
                f"direction {index} must be a JSON object",
            )
        for axis in DIRECTION_AXES:
            if not direction.get(axis):
                return fail(
                    "direction_missing_axis",
                    f"direction {index} is missing {axis}; every direction needs a hook and a payoff",
                )
        if direction.get("recommended") is True:
            recommended += 1
    if recommended != 1:
        return fail(
            "recommendation_not_single",
            "exactly one of the three directions must be recommended",
        )
    numbers = story.get("numbers")
    if not isinstance(numbers, list):
        return fail(
            "numbers_missing",
            "story must list its numbers, each with a source and a read time",
        )
    for index, number in enumerate(numbers):
        if not isinstance(number, dict):
            return fail(
                "number_not_object",
                f"number {index} must be a JSON object",
            )
        if not number.get("source"):
            return fail(
                "number_missing_source",
                f"number {index} states no source; every number must cite its source",
            )
        if not number.get("read_at"):
            return fail(
                "number_missing_read_time",
                f"number {index} states no read time; every number must state when it was read",
            )
    for index, point in enumerate(story.get("turning_points", [])):
        if isinstance(point, dict) and point.get("invented") is True:
            return fail(
                "invented_turning_point",
                f"turning point {index} was invented rather than found; invented turning points fail",
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
    report = check_creator_story(params.get("story"))
    report_path = out_dir / "creator_story_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_creator_story_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.creator_story_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "story": {"type": "object"},
                },
                "required": ["story"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Creator story gate: person before event, three "
                "directions each with hook and payoff and one "
                "recommended, numbers sourced and dated, no invented "
                "turning points."
            ),
        )
    )
    return ["qa.creator_story_gate"]


__all__ = [
    "DIRECTION_AXES",
    "check_creator_story",
    "register_creator_story_gate_capabilities_once",
]
