"""Sequence-level planning and continuity diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

from hevi.cinematic.shot_intelligence.models import ShotIntent, ShotPlan
from hevi.cinematic.shot_intelligence.selector import ShotSelector


@dataclass(frozen=True)
class SequenceResult:
    plan: ShotPlan
    diagnostics: tuple[str, ...]


class SequencePlanner:
    def __init__(self, selector: ShotSelector | None = None) -> None:
        self.selector = selector or ShotSelector()

    def plan(self, intents: list[ShotIntent]) -> SequenceResult:
        result = self.selector.plan(intents)
        diagnostics: list[str] = []
        names = [shot.shot_type for shot in result.shots]
        if any(a == b for a, b in pairwise(names)):
            diagnostics.append("repeated_shot_type")
        if len(names) >= 4 and len(set(names)) <= 2:
            diagnostics.append("pacing_monotony")
        if sum(shot.framing == "close" for shot in result.shots) > max(2, len(result.shots) * 0.6):
            diagnostics.append("excessive_closeups")
        if sum(shot.camera_motion.name == "static" for shot in result.shots) > max(3, len(result.shots) * 0.8):
            diagnostics.append("excessive_static_shots")
        return SequenceResult(ShotPlan(result.line, result.shots, result.beat_cues, tuple(diagnostics)), tuple(diagnostics))
