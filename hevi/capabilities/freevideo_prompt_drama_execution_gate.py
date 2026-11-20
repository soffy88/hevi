"""Six-section prompt + drama execution gate (``qa.freevideo_prompt_drama_execution_gate``).

This gate adds only what the Eian seven-section prompt gate
(``qa.seven_section_prompt_gate``) and the dance H3 prompt
gate (``qa.dance_h3_prompt_gate``) do not already cover: the
drama execution rules. In the reviewer's own words, a plan
fails when the six sections are not exactly the H3 six in
order, when a shot is not 15 to 20 seconds (at most 15
seconds with a cast card or reference pictures, never 3 to
6 seconds, and never above the device limit), when an
in-shot ``[Shot N]`` cut is not 2 to 4 seconds, when a cast
card exists but its wardrobe is not fixed for the whole
film, when any of the five pre-generation faults is left
unchecked (stray lettering, small faces in wide shots, text
under 14 pixels, third-party marks, voice references), when
speakers are not numbered by first spoken line, when
dialogue is not word for word, or when an agent plan runs
without plan-before-run. The gate judges plan descriptions
only; it generates no video and spends nothing.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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
from hevi.capabilities.scene_reference import H3_SECTIONS

_Registered = False

PRE_GENERATION_CHECKS: tuple[str, ...] = (
    "stray_lettering",
    "small_faces_wide_shot",
    "text_under_14px",
    "third_party_marks",
    "voice_references",
)
SHOT_SECONDS_MIN = 15
SHOT_SECONDS_MAX = 20
CAST_SHOT_SECONDS_MAX = 15
FORBIDDEN_SHOT_SECONDS = (3, 4, 5, 6)
CUT_SECONDS_MIN = 2
CUT_SECONDS_MAX = 4
MAX_CUTS_PER_SHOT = 6


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_freevideo_prompt_drama_execution(plan: Any) -> dict[str, Any]:
    """Validate a FreeVideo-style prompt + drama execution plan.

    Verdicts are ``pass`` / ``fail`` only. A plan fails when
    a required field is missing, when the six sections are
    not exactly the H3 six in order, when the shot length
    breaks the 15–20 second rule (at most 15 with a cast
    card or references, never 3–6 seconds, never above the
    device limit), when an in-shot cut is not 2–4 seconds or
    there are more than six cuts, when a cast card's wardrobe
    is not fixed, when any of the five pre-generation faults
    is unchecked, when speakers are not numbered by first
    line, when dialogue is not word for word, or when an
    agent plan runs without plan-before-run.
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
        return fail("plan_not_object", "drama execution plan must be a JSON object")
    for field in (
        "six_sections",
        "shot_seconds",
        "pre_generation_checks",
        "speakers_numbered_by_first_line",
        "dialogue_word_for_word",
    ):
        if field not in plan:
            return fail("plan_field_missing", f"drama execution plan must carry {field!r}")
    if plan["six_sections"] != list(H3_SECTIONS):
        return fail(
            "six_sections_wrong_order",
            "six_sections must be exactly the H3 six in order: " + ", ".join(H3_SECTIONS),
        )
    seconds = plan["shot_seconds"]
    if not _is_number(seconds) or seconds <= 0:
        return fail("shot_seconds_invalid", "shot_seconds must be a positive number")
    if seconds in FORBIDDEN_SHOT_SECONDS:
        return fail(
            "shot_seconds_forbidden",
            f"never write {int(seconds)}-second shots",
        )
    device_limit = plan.get("device_limit_seconds")
    if device_limit is not None:
        if not _is_number(device_limit) or device_limit <= 0:
            return fail(
                "device_limit_invalid",
                "device_limit_seconds must be a positive number",
            )
        if seconds > device_limit:
            return fail(
                "shot_seconds_over_device_limit",
                f"shot_seconds {seconds} exceeds the device limit {device_limit}",
            )
    elif plan.get("has_cast_card") is True or plan.get("references"):
        if seconds > CAST_SHOT_SECONDS_MAX:
            return fail(
                "cast_shot_too_long",
                "a shot with a cast card or reference pictures is at most "
                f"{CAST_SHOT_SECONDS_MAX} seconds, got {seconds}",
            )
    elif seconds < SHOT_SECONDS_MIN or seconds > SHOT_SECONDS_MAX:
        return fail(
            "shot_seconds_out_of_range",
            f"shot_seconds must be {SHOT_SECONDS_MIN}..{SHOT_SECONDS_MAX}, got {seconds}",
        )
    cuts = plan.get("shot_cuts")
    if cuts is not None:
        if not isinstance(cuts, list) or not cuts:
            return fail("shot_cuts_invalid", "shot_cuts must be a non-empty list")
        if len(cuts) > MAX_CUTS_PER_SHOT:
            return fail(
                "too_many_cuts",
                f"at most {MAX_CUTS_PER_SHOT} cuts per shot, got {len(cuts)}",
            )
        for position, cut in enumerate(cuts):
            if not isinstance(cut, dict):
                return fail("cut_not_object", f"cut {position} must be an object")
            duration = cut.get("duration_s")
            if not _is_number(duration) or not (CUT_SECONDS_MIN <= duration <= CUT_SECONDS_MAX):
                return fail(
                    "cut_duration_out_of_range",
                    f"cut {position} must be {CUT_SECONDS_MIN}..{CUT_SECONDS_MAX} "
                    f"seconds, got {duration!r}",
                )
    if plan.get("has_cast_card") is True and plan.get("cast_wardrobe_fixed") is not True:
        return fail(
            "cast_wardrobe_not_fixed",
            "a cast card fixes clothes for the whole film; cast_wardrobe_fixed must be true",
        )
    checks = plan["pre_generation_checks"]
    if not isinstance(checks, dict):
        return fail(
            "pre_generation_checks_not_object",
            "pre_generation_checks must be an object",
        )
    for fault in PRE_GENERATION_CHECKS:
        if checks.get(fault) is not True:
            return fail(
                "pre_generation_fault_unchecked",
                f"pre-generation fault {fault!r} must be checked before generating",
            )
    if plan["speakers_numbered_by_first_line"] is not True:
        return fail(
            "speakers_not_numbered",
            "speakers must be numbered by order of first spoken line",
        )
    if plan["dialogue_word_for_word"] is not True:
        return fail(
            "dialogue_not_word_for_word",
            "dialogue must be written word for word",
        )
    agent = plan.get("agent")
    if agent is not None:
        if not isinstance(agent, dict):
            return fail("agent_not_object", "agent must be an object")
        if agent.get("plan_before_run") is not True:
            return fail(
                "plan_before_run_required",
                "an agent plan must run plan-before-run",
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
    report = check_freevideo_prompt_drama_execution(params.get("plan"))
    report_path = out_dir / "freevideo_prompt_drama_execution_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_prompt_drama_execution_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_prompt_drama_execution_gate",
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
                "FreeVideo prompt + drama execution gate (increment "
                "over the Eian seven-section and dance H3 prompt "
                "gates): H3 six sections in order, shots 15–20 "
                "seconds (at most 15 with cast or references, never "
                "3–6), cuts 2–4 seconds, cast wardrobe fixed, five "
                "pre-generation faults checked, speakers numbered by "
                "first line, dialogue word for word, plan-before-run."
            ),
        )
    )
    return ["qa.freevideo_prompt_drama_execution_gate"]


__all__ = [
    "CAST_SHOT_SECONDS_MAX",
    "CUT_SECONDS_MAX",
    "CUT_SECONDS_MIN",
    "FORBIDDEN_SHOT_SECONDS",
    "MAX_CUTS_PER_SHOT",
    "PRE_GENERATION_CHECKS",
    "SHOT_SECONDS_MAX",
    "SHOT_SECONDS_MIN",
    "check_freevideo_prompt_drama_execution",
    "register_freevideo_prompt_drama_execution_gate_capabilities_once",
]
