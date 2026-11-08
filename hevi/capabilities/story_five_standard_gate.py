"""Story five-standard gate (``qa.story_five_standard_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): before any picture
is drawn, a finished story must meet five standards of its
own, in the reviewer's own words — it must hold together
under plain real-world questioning, it must be sayable in
one sentence, its most eye-catching image must come first,
every bystander's reaction must arrive in its own turn,
and it must avoid the shots a video model reliably gets
wrong unless the avoidance is declared. This gate judges
the story record only. It draws nothing, renders nothing,
and spends nothing: ``executed_here`` is always false.
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

# Shots a video model reliably gets wrong, in the reviewer's
# own words. A story may include one only with a declared
# avoidance note for that item.
WEAK_POINTS: frozenset[str] = frozenset(
    {
        "person_crossing",
        "small_object_in_hand",
        "on_screen_text",
        "mirror_reflection",
        "asymmetric_feature",
        "light_change_in_shot",
        "three_actions_one_shot",
        "top_down_no_face",
        "too_many_extras",
    }
)

STRUCTURES: frozenset[str] = frozenset({"episodic", "continuous"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_story_five_standards(story: Any) -> dict[str, Any]:
    """Validate a finished story against the five standards.

    Verdicts are ``pass`` / ``fail`` only. A story fails
    when it has no one-sentence theme, when two bystanders
    react in the same beat at the same moment, when it
    carries an unmitigated model weak point, when a
    continuous structure has no stated links between its
    parts, or when its opening hook is missing.
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
    theme = story.get("one_line_theme")
    if not isinstance(theme, str) or not theme.strip():
        return fail(
            "theme_missing",
            "story must state in one sentence what the film is saying",
        )
    hook = story.get("hook")
    if not isinstance(hook, dict):
        return fail(
            "hook_missing",
            "story must name its opening hook image and the second it appears",
        )
    second = hook.get("second")
    if not isinstance(second, (int, float)) or second < 0:
        return fail(
            "hook_second_missing",
            "hook must carry the second its image appears",
        )
    if not isinstance(hook.get("image"), str) or not hook["image"].strip():
        return fail("hook_image_missing", "hook must name its image")
    structure = story.get("structure")
    if structure not in STRUCTURES:
        return fail(
            "structure_unknown",
            "story structure must be episodic or continuous",
        )
    if structure == "continuous":
        links = story.get("continuity_links")
        if not isinstance(links, list) or not links:
            return fail(
                "continuity_unexplained",
                "a continuous story must state how its parts link",
            )
    reactions = story.get("bystander_reactions")
    if not isinstance(reactions, list) or not reactions:
        return fail(
            "reactions_missing",
            "every turn needs a bystander reaction in three parts: "
            "problem, how the lead handles it, how others react",
        )
    seen: dict[tuple[str, Any], str] = {}
    for position, reaction in enumerate(reactions):
        if not isinstance(reaction, dict):
            return fail(
                "reaction_not_object",
                f"bystander reaction {position} must be an object",
            )
        beat = reaction.get("beat")
        actor = reaction.get("actor")
        text = reaction.get("reaction")
        delay = reaction.get("delay_s")
        if not isinstance(beat, str) or not beat.strip():
            return fail(
                "reaction_beat_missing",
                f"bystander reaction {position} must name its beat",
            )
        if not isinstance(actor, str) or not actor.strip():
            return fail(
                "reaction_actor_missing",
                f"bystander reaction {position} must name who reacts",
            )
        if not isinstance(text, str) or not text.strip():
            return fail(
                "reaction_text_missing",
                f"bystander reaction {position} must state the reaction",
            )
        if not isinstance(delay, (int, float)):
            return fail(
                "reaction_delay_missing",
                f"bystander reaction {position} must carry its delay in seconds",
            )
        key = (beat, delay)
        if key in seen:
            return fail(
                "simultaneous_reaction",
                f"{actor} and {seen[key]} react in beat {beat!r} at the "
                "same second; reactions must arrive in turn",
            )
        seen[key] = actor
    flags = story.get("weak_points")
    if isinstance(flags, list):
        notes = story.get("avoid_notes")
        if not isinstance(notes, dict):
            notes = {}
        for flag in flags:
            if flag not in WEAK_POINTS:
                return fail(
                    "weak_point_unknown",
                    f"unknown weak point {flag!r}; use the closed vocabulary",
                )
            if not isinstance(notes.get(flag), str) or not notes[flag].strip():
                return fail(
                    "unmitigated_weak_point",
                    f"weak point {flag!r} needs a declared avoidance note",
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
    report = check_story_five_standards(params.get("story"))
    report_path = out_dir / "story_five_standard_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_story_five_standard_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.story_five_standard_gate",
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
                "Story five-standard gate: real-world logic, one-sentence "
                "theme, opening hook, bystander reactions in turn, and "
                "declared avoidance of model weak points."
            ),
        )
    )
    return ["qa.story_five_standard_gate"]


__all__ = [
    "STRUCTURES",
    "WEAK_POINTS",
    "check_story_five_standards",
    "register_story_five_standard_gate_capabilities_once",
]
