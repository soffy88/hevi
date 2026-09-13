"""Narrative quality gate with explicit hard failures and soft warnings."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.continuity import ContinuityReport
from hevi.narrative.models import SceneBlueprint, StoryBible


@dataclass(frozen=True)
class NarrativeQualityReport:
    status: str
    findings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status != "FAIL"


class NarrativeQualityGate:
    def evaluate(self, bible: StoryBible, scene: SceneBlueprint, continuity: ContinuityReport) -> NarrativeQualityReport:
        findings: list[object] = list(continuity.findings)
        if not scene.purpose:
            findings.append("scene missing purpose")
        if any(finding.get("severity") == "FAIL" for finding in continuity.findings):
            return NarrativeQualityReport("FAIL", tuple(str(item.get("code")) for item in findings if isinstance(item, dict)))
        if not scene.objective.text:
            return NarrativeQualityReport("FAIL", ("scene missing purpose",))
        warnings = [str(item.get("code")) for item in findings if isinstance(item, dict)]
        if not any(beat.change for episode in bible.episodes for beat in episode.beats):
            warnings.append("NO_DRAMATIC_CHANGE")
        return NarrativeQualityReport("WARN" if warnings else "PASS", tuple(warnings))
