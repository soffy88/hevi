"""What-if script format gate (``qa.whatif_script_format_gate``).

Discipline gate only. A "what would happen if" explainer
script must follow the six-beat format, in order: an opening
hook, a common misconception, a turn, escalating examples,
the mechanism, and a closing answer. Every beat must be
present exactly once, in that order, with non-empty text.
Facts in the script must be declared checked, and any
theoretical claim must be declared hedged. The format is a
method reference only: it carries no affiliation with any
named creator, and no view-count claim is made here. This
gate judges the script plan only and renders nothing. See
ANIMATION_SKILLS_ATTRIBUTION.md.
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

# Six-beat format, restated in hevi's own words. The order is
# part of the format: the turn only lands after the
# misconception, and the mechanism only lands after the
# examples have earned it.
BEATS = (
    "hook",
    "misconception",
    "but_turn",
    "examples",
    "mechanism",
    "closing",
)


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_whatif_script(plan: Any) -> dict[str, Any]:
    """Check a what-if script plan against the six-beat format.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Missing, duplicated, out-of-order, or
    empty beats fail, as do unchecked facts and unhedged
    theoretical claims.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    sections = plan.get("sections")
    if not isinstance(sections, list) or not sections:
        issues.append(
            _issue("sections_missing", "plan must declare a non-empty sections list")
        )
        sections = sections if isinstance(sections, list) else []
    kinds: list[str] = []
    for index, section in enumerate(sections):
        label = f"sections[{index}]"
        if not isinstance(section, dict):
            issues.append(
                _issue(f"{label}:not_object", "each section must be an object")
            )
            continue
        kind = section.get("kind")
        kinds.append(kind if isinstance(kind, str) else "")
        if kind not in BEATS:
            issues.append(
                _issue(
                    f"{label}:unknown_beat",
                    f"section kind must be one of {', '.join(BEATS)}",
                )
            )
        text = section.get("text")
        if not isinstance(text, str) or not text.strip():
            issues.append(
                _issue(f"{label}:text_empty", "each beat must carry non-empty text")
            )
    if kinds != list(BEATS):
        issues.append(
            _issue(
                "beat_sequence_wrong",
                "beats must appear exactly once each, in order: "
                + ", ".join(BEATS),
            )
        )
    if plan.get("fact_checked") is not True:
        issues.append(
            _issue(
                "facts_unchecked",
                "script facts must be declared checked before "
                "the script passes",
            )
        )
    if plan.get("theory_claims") is True and plan.get("hedging_present") is not True:
        issues.append(
            _issue(
                "theory_unhedged",
                "theoretical claims must be declared hedged",
            )
        )
    if plan.get("affiliation_claimed") is True:
        issues.append(
            _issue(
                "affiliation_claimed",
                "the format carries no affiliation with any "
                "named creator; affiliation claims fail",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "beats": list(BEATS),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_whatif_script(params.get("plan"))
    report_path = out_dir / "whatif_script_format.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_whatif_script_format_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.whatif_script_format_gate",
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
                "What-if script format gate: hook, misconception, "
                "turn, examples, mechanism, and closing in order, "
                "facts declared checked, theoretical claims "
                "hedged, no creator affiliation claimed."
            ),
        )
    )
    return ["qa.whatif_script_format_gate"]


__all__ = [
    "check_whatif_script",
    "register_whatif_script_format_gate_capabilities_once",
]
