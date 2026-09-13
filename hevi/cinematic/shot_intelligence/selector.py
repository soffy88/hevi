"""Deterministic recipe selection; no renderer/provider imports."""

from __future__ import annotations

import os

from hevi.cinematic.shot_intelligence.catalog import default_catalog
from hevi.cinematic.shot_intelligence.models import (
    ShotIntent,
    ShotPlan,
    ShotRecipe,
    ShotSelectionResult,
)


def enabled() -> bool:
    return os.getenv("SHOT_INTELLIGENCE_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


class ShotSelector:
    def __init__(self, catalog: tuple[ShotRecipe, ...] | None = None) -> None:
        self.catalog = catalog or default_catalog()

    def select(self, intent: ShotIntent) -> ShotSelectionResult:
        candidates = list(self.catalog)
        if intent.dialogue_present:
            candidates = [r for r in candidates if r.dialogue_compatible]
        if intent.narration_present and not intent.dialogue_present:
            candidates = [r for r in candidates if r.narration_compatible]
        if intent.narrative_purpose in {"hook", "cta"}:
            preferred = [r for r in candidates if intent.narrative_purpose in r.tags]
            candidates = preferred or candidates
        elif intent.narrative_purpose == "establishing":
            preferred = [r for r in candidates if r.shot_type == "establishing" or "wide" in r.tags]
            candidates = preferred or candidates
        elif intent.narrative_purpose in {"action", "evidence"}:
            preferred = [r for r in candidates if r.shot_type in {"b_roll", "detail", "coverage"}]
            candidates = preferred or candidates
        if intent.target_duration_s > 0:
            fitting = [r for r in candidates if r.duration_range_s[0] <= intent.target_duration_s <= r.duration_range_s[1]]
            candidates = fitting or candidates
        if not candidates:
            raise ValueError("no shot recipe satisfies the requested intent")
        selected = sorted(candidates, key=lambda r: (r.shot_type != "coverage", r.id))[0]
        confidence = 0.9 if selected.duration_range_s[0] <= intent.target_duration_s <= selected.duration_range_s[1] else 0.65
        return ShotSelectionResult(
            selected=selected,
            confidence=confidence,
            rationale=f"selected {selected.id} for {intent.narrative_purpose} at {intent.pacing} pacing",
            alternatives=tuple(r for r in candidates if r.id != selected.id)[:3],
            renderer_projection=project_shot(selected),
            validation_constraints=selected.constraints,
        )

    def plan(self, intents: list[ShotIntent]) -> ShotPlan:
        results = [self.select(i) for i in intents]
        return ShotPlan(
            line=intents[0].line if intents else "",
            shots=tuple(r.selected for r in results),
            beat_cues=tuple(cue for intent in intents for cue in intent.beat_map),
        )


def project_shot(recipe: ShotRecipe) -> dict[str, object]:
    """Provider-neutral projection data; canonical recipe remains unchanged."""
    return {"shot_type": recipe.shot_type, "framing": recipe.framing, "camera_motion": recipe.camera_motion.name, "duration_range_s": recipe.duration_range_s}
