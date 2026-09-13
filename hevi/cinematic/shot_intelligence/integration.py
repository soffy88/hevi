"""Opt-in integration boundary for existing lines."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.models import ShotIntent, ShotPlan
from hevi.cinematic.shot_intelligence.selector import ShotSelector, enabled
from hevi.cinematic.shot_intelligence.sequence import SequencePlanner

WIRED_LINES = frozenset({"kinetic_promo", "explainer", "reference_adapt", "shorts_clip", "cinematic", "director_pipeline"})


def plan_for_line(line: str, intents: list[ShotIntent]) -> ShotPlan | None:
    """Return a plan only when the opt-in flag is enabled for a wired line."""
    if not enabled() or line not in WIRED_LINES:
        return None
    if any(intent.line != line for intent in intents):
        raise ValueError("all shot intents must belong to the requested line")
    return SequencePlanner(ShotSelector()).plan(intents).plan


def plan_with_fallback(
    line: str,
    intents: list[ShotIntent],
    *,
    existing_planner: object,
) -> tuple[ShotPlan | None, dict[str, object]]:
    """Use Shot Intelligence when enabled, otherwise make fallback explicit.

    ``existing_planner`` is intentionally opaque: the canonical planner never
    imports a renderer or provider.  Callers persist the returned provenance.
    """

    if not enabled() or line not in WIRED_LINES:
        return None, {"shot_intelligence_used": False, "fallback_reason": "feature_disabled_or_line_not_wired"}
    try:
        return plan_for_line(line, intents), {"shot_intelligence_used": True}
    except (TypeError, ValueError, KeyError) as exc:
        if existing_planner is None:
            raise
        return None, {"shot_intelligence_used": False, "fallback_reason": f"{type(exc).__name__}:{exc}"}
