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

