"""HEVI P5.3 — Reference grammar: VIDEO -> ABSTRACT GRAMMAR.

Extracts abstract grammar from a reference video: pacing signature, shot
duration distribution, composition families, camera families, transition
families, motion language, speaker/evidence pattern, information density
curve, narrative arc, caption behavior, audio-visual relationship, and
distinctive patterns.

This is NOT VIDEO -> COPY SHOT LIST. It captures distributions, families,
relationships, and general pacing — never ordered shot sequences, timing
vectors, or asset sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hevi.production.p5_3.schema import ReferenceGrammar, SourceProvenance


@dataclass
class ReferenceVideoAnalysis:
    """Analysis of a reference video, producing an abstract grammar."""

    reference_id: str
    duration_s: float = 0.0
    shot_count: int = 0
    shot_durations: list[float] = field(default_factory=list)
    composition_labels: list[str] = field(default_factory=list)
    camera_labels: list[str] = field(default_factory=list)
    transition_labels: list[str] = field(default_factory=list)
    motion_labels: list[str] = field(default_factory=list)
    caption_segments: list[dict[str, Any]] = field(default_factory=list)
    speaker_segments: list[dict[str, Any]] = field(default_factory=list)
    evidence_segments: list[dict[str, Any]] = field(default_factory=list)

    def to_grammar(self) -> ReferenceGrammar:
        """Convert analysis to abstract grammar.

        Extracts distributions and families, never ordered sequences.
        """
        return ReferenceGrammar(
            reference_id=self.reference_id,
            pacing_signature=self._pacing_signature(),
            shot_duration_distribution=self._duration_distribution(),
            composition_families=self._families(self.composition_labels),
            camera_families=self._families(self.camera_labels),
            transition_families=self._families(self.transition_labels),
            motion_language=self._families(self.motion_labels),
            speaker_evidence_pattern=self._speaker_evidence_pattern(),
            information_density_curve=self._density_curve(),
            narrative_arc=self._narrative_arc(),
            caption_behavior=self._caption_behavior(),
            audio_visual_relationship=self._audio_visual_relationship(),
            distinctive_patterns=self._distinctive_patterns(),
            source_provenance=SourceProvenance(
                origin="reference_derived",
                source_repository=self.reference_id,
            ),
        )

    def _pacing_signature(self) -> str:
        """Abstract pacing signature: fast/mixed/slow."""
        if not self.shot_durations:
            return "unknown"
        avg = sum(self.shot_durations) / len(self.shot_durations)
        if avg < 2.0:
            return "fast_cut"
        if avg > 6.0:
            return "slow_hold"
        return "mixed_pacing"

    def _duration_distribution(self) -> dict[str, float]:
        """Shot duration distribution as percentages."""
        if not self.shot_durations:
            return {}
        total = len(self.shot_durations)
        fast = sum(1 for d in self.shot_durations if d < 2.0) / total
        medium = sum(1 for d in self.shot_durations if 2.0 <= d <= 6.0) / total
        slow = sum(1 for d in self.shot_durations if d > 6.0) / total
        return {"fast": round(fast, 3), "medium": round(medium, 3), "slow": round(slow, 3)}

    def _families(self, labels: list[str]) -> list[str]:
        """Extract unique family labels."""
        seen: set[str] = set()
        result: list[str] = []
        for label in labels:
            if label and label not in seen:
                seen.add(label)
                result.append(label)
        return result

    def _speaker_evidence_pattern(self) -> str:
        """Abstract speaker/evidence pattern."""
        has_speaker = bool(self.speaker_segments)
        has_evidence = bool(self.evidence_segments)
        if has_speaker and has_evidence:
            return "speaker_with_evidence"
        if has_speaker:
            return "speaker_only"
        if has_evidence:
            return "evidence_only"
        return "neither"

    def _density_curve(self) -> list[float]:
        """Information density curve as a list of values."""
        if not self.shot_durations:
            return []
        # Simplified: density inversely related to shot duration
        return [round(max(0.1, min(1.0, 5.0 / max(d, 0.5))), 3) for d in self.shot_durations]

    def _narrative_arc(self) -> str:
        """Abstract narrative arc."""
        if not self.shot_durations:
            return "unknown"
        if len(self.shot_durations) < 3:
            return "flat"
        first = sum(self.shot_durations[: len(self.shot_durations) // 3]) / max(1, len(self.shot_durations) // 3)
        last = sum(self.shot_durations[-(len(self.shot_durations) // 3):]) / max(1, len(self.shot_durations) // 3)
        if last > first * 1.5:
            return "decelerating"
        if first > last * 1.5:
            return "accelerating"
        return "steady"

    def _caption_behavior(self) -> str:
        """Abstract caption behavior."""
        if not self.caption_segments:
            return "none"
        has_sync = any(s.get("synced", False) for s in self.caption_segments)
        return "synced" if has_sync else "unsynced"

    def _audio_visual_relationship(self) -> str:
        """Abstract audio-visual relationship."""
        if not self.speaker_segments and not self.evidence_segments:
            return "music_only"
        if self.speaker_segments and self.evidence_segments:
            return "narration_with_evidence"
        if self.speaker_segments:
            return "narration_only"
        return "evidence_only"

    def _distinctive_patterns(self) -> list[str]:
        """Distinctive patterns: abstract, not copyable sequences."""
        patterns: list[str] = []
        if self._pacing_signature() == "fast_cut":
            patterns.append("rapid_pacing")
        if self._pacing_signature() == "slow_hold":
            patterns.append("deliberate_pacing")
        if self._speaker_evidence_pattern() == "speaker_with_evidence":
            patterns.append("presenter_evidence_balance")
        return patterns


__all__ = ["ReferenceVideoAnalysis"]
