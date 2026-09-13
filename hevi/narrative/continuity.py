"""Continuity checks that report findings without mutating canonical state."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.models import EpisodeBlueprint, SceneBlueprint, StoryBible


@dataclass(frozen=True)
class ContinuityReport:
    report_id: str
    status: str
    findings: tuple[dict[str, object], ...] = ()


class ContinuityEngine:
    def check(self, bible: StoryBible, scenes: tuple[SceneBlueprint, ...] = (), episode: EpisodeBlueprint | None = None) -> ContinuityReport:
        findings: list[dict[str, object]] = []
        character_ids = {character.id for character in bible.characters}
        location_ids = {location.id for location in bible.locations}
        fact_ids = {fact.id for fact in bible.established_facts}
        for scene in scenes:
            missing = sorted(set(scene.characters) - character_ids)
            if missing:
                findings.append(self._finding("CHARACTER_STATE_CONFLICT", "FAIL", missing, [scene.scene_id], "scene references unknown characters", "add characters to StoryBible"))
            if location_ids and scene.location not in location_ids:
                findings.append(self._finding("LOCATION_CONFLICT", "FAIL", [scene.location], [scene.scene_id], "scene location is not established", "establish the location"))
            missing_facts = sorted(set(scene.required_facts) - fact_ids)
            if missing_facts:
                findings.append(self._finding("ESTABLISHED_FACT_CONFLICT", "FAIL", missing_facts, [scene.scene_id], "required fact is not in the bible", "add evidence-backed fact"))
            if not scene.purpose or not scene.objective.text:
                findings.append(self._finding("SCENE_PLAN_FAILED", "FAIL", [scene.scene_id], [scene.scene_id], "scene has no purpose/objective", "define the scene objective"))
        if episode and len(set(episode.scene_ids)) != len(episode.scene_ids):
            findings.append(self._finding("TEMPORAL_CONFLICT", "FAIL", [episode.episode_id], list(episode.scene_ids), "episode repeats a scene id", "deduplicate scene order"))
        status = "FAIL" if any(item["severity"] == "FAIL" for item in findings) else "WARN" if findings else "PASS"
        return ContinuityReport(f"continuity-{bible.project_id}-{bible.revision}", status, tuple(findings))

    @staticmethod
    def _finding(code: str, severity: str, entity_refs: list[str], scene_refs: list[str], description: str, resolution: str) -> dict[str, object]:
        return {"code": code, "severity": severity, "entity_refs": entity_refs, "scene_refs": scene_refs, "description": description, "suggested_resolution": resolution}
