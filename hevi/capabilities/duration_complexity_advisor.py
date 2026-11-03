"""Duration complexity advisor (``qa.duration_complexity_advisor``).

Clean-room rewrite of a *method* only: five complexity dimensions,
each scored 0-2, map a knowledge script to one of four narrative
duration tiers, and a declared tier two or more tiers away from the
computed tier earns a reminder, not a silent pass. No text, code, or
asset from any outside repository is copied here. See
VIBE_KNOWLEDGE_ATTRIBUTION.md.

Tier bounds and the narration rate are caller parameters. The advisor
never invents a rate: ``chars_per_second`` is required, and no
fallback rate is baked in.
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

DIMENSIONS = (
    "concept_count",
    "prerequisite_depth",
    "evidence_density",
    "abstraction_level",
    "audience_unfamiliarity",
)

DEFAULT_TIERS = ("glance", "concise", "standard", "deep")
DEFAULT_BOUNDS = (2, 5, 8)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def advise_duration_complexity(assessment: Any) -> dict[str, Any]:
    """Advise a narrative duration tier. Returns a report; never raises.

    The verdict is ``pass`` when the assessment is well formed; a
    two-tier gap is reported under ``reminders`` and does not fail the
    assessment, because the reminder itself is the deliverable.
    """
    issues: list[dict[str, Any]] = []
    reminders: list[dict[str, Any]] = []
    if not isinstance(assessment, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "assessment_not_object",
                    "complexity assessment must be a JSON object",
                )
            ],
            "reminders": [],
            "score": None,
            "computed_tier": None,
            "declared_tier": None,
            "tiers": list(DEFAULT_TIERS),
        }
    tiers = assessment.get("tiers", list(DEFAULT_TIERS))
    if (
        not isinstance(tiers, list)
        or len(tiers) < 2
        or not all(isinstance(tier, str) and tier.strip() for tier in tiers)
    ):
        issues.append(
            _issue(
                "tiers_invalid",
                "tiers must be a list of at least two non-empty names",
            )
        )
        tiers = list(DEFAULT_TIERS)
    bounds = assessment.get("tier_bounds", list(DEFAULT_BOUNDS))
    if (
        not isinstance(bounds, list)
        or len(bounds) != len(tiers) - 1
        or not all(isinstance(bound, int) and not isinstance(bound, bool) for bound in bounds)
        or bounds != sorted(bounds)
    ):
        issues.append(
            _issue(
                "tier_bounds_invalid",
                "tier_bounds must be ascending whole numbers, one fewer "
                "than the number of tiers",
            )
        )
        bounds = list(DEFAULT_BOUNDS[: len(tiers) - 1])
    dimensions = assessment.get("dimensions")
    scores: dict[str, Any] = {}
    if not isinstance(dimensions, dict):
        issues.append(
            _issue(
                "dimensions_missing",
                "assessment must declare a dimensions object",
            )
        )
        dimensions = {}
    for name in DIMENSIONS:
        value = dimensions.get(name) if isinstance(dimensions, dict) else None
        if value is None:
            issues.append(
                _issue(
                    f"dimension_missing:{name}",
                    f"complexity dimension {name!r} is missing",
                )
            )
            continue
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value not in (0, 1, 2)
        ):
            issues.append(
                _issue(
                    f"dimension_invalid:{name}",
                    f"complexity dimension {name!r} must score 0, 1, or 2",
                )
            )
            continue
        scores[name] = value
    extra = (
        [key for key in dimensions if key not in DIMENSIONS]
        if isinstance(dimensions, dict)
        else []
    )
    if extra:
        issues.append(
            _issue(
                "dimension_unknown",
                f"unknown complexity dimensions: {extra}",
            )
        )
    rate = assessment.get("chars_per_second")
    if not _is_number(rate) or rate <= 0:
        issues.append(
            _issue(
                "chars_per_second_missing",
                "chars_per_second is a required caller parameter; the "
                "advisor never assumes a narration rate",
            )
        )
    declared = assessment.get("declared_tier")
    if declared is not None and declared not in tiers:
        issues.append(
            _issue(
                "declared_tier_unknown",
                f"declared tier {declared!r} is not one of {tiers}",
            )
        )
    total = sum(scores.values()) if len(scores) == len(DIMENSIONS) else None
    computed = None
    if total is not None:
        tier_index = 0
        for bound in bounds:
            if total > bound:
                tier_index += 1
        computed = tiers[tier_index]
    if (
        computed is not None
        and declared is not None
        and declared in tiers
        and abs(tiers.index(computed) - tiers.index(declared)) >= 2
    ):
        reminders.append(
            _issue(
                "tier_gap_two_or_more",
                f"declared tier {declared!r} is two or more tiers from "
                f"the computed tier {computed!r} (score {total}); "
                "reconsider the declared tier before producing",
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "reminders": reminders,
        "score": total,
        "computed_tier": computed,
        "declared_tier": declared,
        "tiers": list(tiers),
        "tier_bounds": list(bounds),
        "dimensions_scored": scores,
        "chars_per_second": rate if _is_number(rate) else None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = advise_duration_complexity(params.get("assessment"))
    report_path = out_dir / "duration_complexity.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_duration_complexity_advisor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.duration_complexity_advisor",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "assessment": {"type": "object"},
                },
                "required": ["assessment"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Duration complexity advisor: five 0-2 complexity "
                "dimensions map a script to a narrative duration tier; "
                "a declared tier two or more tiers away earns a "
                "reminder. The narration rate is caller supplied."
            ),
        )
    )
    return ["qa.duration_complexity_advisor"]


__all__ = [
    "advise_duration_complexity",
    "register_duration_complexity_advisor_capabilities_once",
]
