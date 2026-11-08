"""Knowledge-film narrative templates (``story.knowledge_film_templates``).

Clean-room rewrite of a *method* only: six beat skeletons for
single-idea knowledge films, each naming the beats a script must
hit and the most each beat may carry. The wording, the beat names,
and the limits below are this repository's own restatement; no
template text, benchmark number, or worked example from any
outside repository is copied here. See
VIBE_KNOWLEDGE_ATTRIBUTION.md.

This module is data plus validation only. It writes no script and
renders nothing; callers assemble scripts against these skeletons
and judge them with the storyboard and source gates.
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

TEMPLATES: dict[str, dict[str, Any]] = {
    "riddle_concept": {
        "description": (
            "Open with a riddle the viewer cannot answer yet, then "
            "reveal the concept piece by piece until the riddle "
            "resolves itself."
        ),
        "beats": [
            {"role": "riddle", "max_chars": 60},
            {"role": "wrong_guess", "max_chars": 80},
            {"role": "first_clue", "max_chars": 120},
            {"role": "turning_clue", "max_chars": 120},
            {"role": "resolution", "max_chars": 100},
        ],
    },
    "dilemma_choice": {
        "description": (
            "Pose two options that both look right, weigh each with "
            "evidence, then land the choice and name what it costs."
        ),
        "beats": [
            {"role": "dilemma", "max_chars": 60},
            {"role": "option_a", "max_chars": 110},
            {"role": "option_b", "max_chars": 110},
            {"role": "evidence_weighing", "max_chars": 130},
            {"role": "choice_and_cost", "max_chars": 100},
        ],
    },
    "pain_point_principle": {
        "description": (
            "Start from a familiar frustration, show why the usual "
            "fix fails, then state the principle that dissolves it."
        ),
        "beats": [
            {"role": "pain_point", "max_chars": 60},
            {"role": "usual_fix", "max_chars": 90},
            {"role": "why_it_fails", "max_chars": 120},
            {"role": "principle", "max_chars": 110},
            {"role": "application", "max_chars": 100},
        ],
    },
    "single_thread": {
        "description": (
            "Follow one thread from cause to consequence without "
            "branching: each beat hands the next beat its premise."
        ),
        "beats": [
            {"role": "premise", "max_chars": 70},
            {"role": "first_link", "max_chars": 110},
            {"role": "second_link", "max_chars": 110},
            {"role": "consequence", "max_chars": 110},
            {"role": "takeaway", "max_chars": 80},
        ],
    },
    "gauntlet": {
        "description": (
            "Run the idea through a rising series of challenges, "
            "each harder than the last, until only the idea that "
            "survives them all remains."
        ),
        "beats": [
            {"role": "claim", "max_chars": 60},
            {"role": "challenge_one", "max_chars": 100},
            {"role": "challenge_two", "max_chars": 110},
            {"role": "challenge_three", "max_chars": 120},
            {"role": "survivor", "max_chars": 90},
        ],
    },
    "six_facet_rotation": {
        "description": (
            "Rotate one idea through six facets — origin, mechanism, "
            "evidence, limit, rival view, and use — and close by "
            "stacking the facets into one picture."
        ),
        "beats": [
            {"role": "origin", "max_chars": 90},
            {"role": "mechanism", "max_chars": 110},
            {"role": "evidence", "max_chars": 110},
            {"role": "limit", "max_chars": 90},
            {"role": "rival_view", "max_chars": 100},
            {"role": "use", "max_chars": 90},
            {"role": "stacked_picture", "max_chars": 80},
        ],
    },
}


def list_templates() -> list[str]:
    """Return the closed vocabulary of template names."""
    return sorted(TEMPLATES)


def get_template(name: Any) -> dict[str, Any]:
    """Return one template by name, or a failure report for unknown names."""
    if not isinstance(name, str) or name not in TEMPLATES:
        return {
            "ok": False,
            "name": name if isinstance(name, str) else None,
            "known_templates": list_templates(),
            "issue": f"unknown knowledge-film template: {name!r}",
        }
    template = TEMPLATES[name]
    return {
        "ok": True,
        "name": name,
        "description": template["description"],
        "beats": [dict(beat) for beat in template["beats"]],
        "beat_count": len(template["beats"]),
        "max_total_chars": sum(
            beat["max_chars"] for beat in template["beats"]
        ),
    }


def check_script_against_template(script: Any) -> dict[str, Any]:
    """Check a beat-role script against its declared template.

    ``script`` is ``{"template": name, "beats": [{"role": str,
    "text": str}]}``. Roles must follow the template order exactly;
    each beat's text must fit the template's per-beat character
    limit. Returns a report; never raises.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(script, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [{"code": "script_not_object", "detail": "script must be a JSON object"}],
            "template": None,
        }
    name = script.get("template")
    template = get_template(name)
    if not template["ok"]:
        issues.append(
            {"code": "template_unknown", "detail": template["issue"]}
        )
        return {
            "verdict": "fail",
            "ok": False,
            "issues": issues,
            "template": name,
        }
    beats = script.get("beats")
    if not isinstance(beats, list) or not beats:
        issues.append(
            {"code": "beats_missing", "detail": "script must declare a non-empty beats list"}
        )
        beats = beats if isinstance(beats, list) else []
    expected = template["beats"]
    if len(beats) != len(expected):
        issues.append(
            {
                "code": "beat_count_mismatch",
                "detail": f"template {name!r} needs {len(expected)} beats, "
                f"script has {len(beats)}",
            }
        )
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            issues.append(
                {"code": f"beats[{index}]:not_object", "detail": "each beat must be an object"}
            )
            continue
        if index >= len(expected):
            break
        want = expected[index]
        if beat.get("role") != want["role"]:
            issues.append(
                {
                    "code": f"beats[{index}]:role_mismatch",
                    "detail": f"beat {index} must play role {want['role']!r}, "
                    f"got {beat.get('role')!r}",
                }
            )
        text = beat.get("text")
        if not isinstance(text, str) or not text.strip():
            issues.append(
                {"code": f"beats[{index}]:text_missing", "detail": "each beat must carry text"}
            )
        elif len(text) > want["max_chars"]:
            issues.append(
                {
                    "code": f"beats[{index}]:text_too_long",
                    "detail": f"beat {index} is {len(text)} characters, "
                    f"over the {want['max_chars']} limit for role "
                    f"{want['role']!r}",
                }
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "template": name,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_script_against_template(params.get("script"))
    report_path = out_dir / "knowledge_film_template.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_knowledge_film_templates_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.knowledge_film_templates",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "script": {"type": "object"},
                },
                "required": ["script"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Knowledge-film narrative templates: six beat "
                "skeletons with per-beat character limits; scripts "
                "are checked role by role against their template."
            ),
        )
    )
    return ["story.knowledge_film_templates"]


__all__ = [
    "TEMPLATES",
    "list_templates",
    "get_template",
    "check_script_against_template",
    "register_knowledge_film_templates_capabilities_once",
]
