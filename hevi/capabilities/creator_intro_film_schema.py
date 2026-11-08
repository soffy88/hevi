"""Creator intro film schema (``video.creator_intro_film_schema``).

Fake-level contract for a creator intro film of the kind
described in the ChrisHKAI-Video creator-intro review (see
``CHRISHKAI_VIDEO_ATTRIBUTION.md``): template, theme, story,
segments and sound, with the six-step flow (environment
check, link and framing, research and story, toy, storyboard,
render) and a 16:9 or 9:16 frame. The contract certifies the
shape of the plan only. It renders nothing and holds no key
and no footage: any plan claiming a film was rendered here
fails outright. Every compiled contract declares
``executed_here: false``, and real rendering is a separate
case.
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

# The six steps of the reviewed flow, in order.
STEPS: tuple[str, ...] = (
    "environment_check",
    "link_and_framing",
    "research_and_story",
    "toy",
    "storyboard",
    "render",
)
ASPECTS: tuple[str, ...] = ("16:9", "9:16")


def compile_creator_intro_film(plan: Any) -> dict[str, Any]:
    """Compile one creator intro film contract.

    ``plan`` carries ``template``, ``theme``, ``story``,
    ``segments``, ``sound``, ``duration_s``, ``aspect`` and
    ``steps``. Raises :class:`CapabilityError` on any shape
    violation, on a step list that is not the six reviewed
    steps in order, on an unsupported aspect, or on any claim
    that a film was rendered here. The returned contract
    records that nothing was executed here.
    """
    if not isinstance(plan, dict):
        raise CapabilityError("Creator intro film plan must be an object")
    if plan.get("executed_here") is True or plan.get("rendered_here") is True:
        raise CapabilityError("film render claims are refused here; this contract executes nothing")
    for key in ("api_key", "grok_api_key", "x_password"):
        if key in plan:
            raise CapabilityError("keys and passwords are never embedded in a film plan")
    for field in ("template", "theme", "story", "sound"):
        if not plan.get(field):
            raise CapabilityError(f"Creator intro film plan requires {field}")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise CapabilityError("Creator intro film plan requires a non-empty segments list")
    duration = plan.get("duration_s")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        raise CapabilityError("Creator intro film plan requires duration_s in seconds")
    if duration < 15 or duration > 60:
        raise CapabilityError("Creator intro film duration must be between 15 and 60 seconds")
    aspect = plan.get("aspect")
    if aspect not in ASPECTS:
        raise CapabilityError("Creator intro film aspect must be 16:9 or 9:16")
    steps = plan.get("steps")
    if not isinstance(steps, list) or [str(step) for step in steps] != list(STEPS):
        raise CapabilityError("Creator intro film steps must be the six reviewed steps in order")
    return {
        "contract": "creator-intro-film",
        "template": plan["template"],
        "theme": plan["theme"],
        "story": plan["story"],
        "segments": list(segments),
        "sound": plan["sound"],
        "duration_s": duration,
        "aspect": aspect,
        "steps": list(STEPS),
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = compile_creator_intro_film(params.get("plan"))
    report_path = out_dir / "creator_intro_film_contract.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "aspect": report["aspect"],
            "executed_here": False,
        },
    )


def register_creator_intro_film_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.creator_intro_film_schema",
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
                "Creator intro film contract (fake): template, theme, "
                "story, segments, sound, six-step flow, 16:9 or 9:16; "
                "no key, no render."
            ),
        )
    )
    return ["video.creator_intro_film_schema"]


__all__ = [
    "ASPECTS",
    "STEPS",
    "compile_creator_intro_film",
    "register_creator_intro_film_schema_capabilities_once",
]
