"""Case analysis projections built on the existing Video Intelligence observer."""

from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field

from .case_models import AssetRef, CaseShot, VideoCase
from .models import ReelAnalysis, StrictModel


class ActionPhase(StrEnum):
    PRE_CONTACT = "pre_contact"
    CONTACT = "contact"
    POST_CONTACT = "post_contact"


class PromptStructure(StrictModel):
    subject: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    visual_style: list[str] = Field(default_factory=list)
    composition: list[str] = Field(default_factory=list)
    action: list[str] = Field(default_factory=list)
    camera: list[str] = Field(default_factory=list)
    temporal_sequence: list[str] = Field(default_factory=list)
    lighting: list[str] = Field(default_factory=list)
    audio: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    instruction_count: int = 0
    action_count: int = 0
    camera_instruction_count: int = 0
    temporal_event_count: int = 0
    reference_binding_count: int = 0


class TemporalComplexity(StrictModel):
    duration_s: float
    distinct_actions: int = Field(ge=0)
    camera_events: int = Field(ge=0)
    subject_state_changes: int = Field(ge=0)
    scene_state_changes: int = Field(ge=0)
    complexity_score: float = Field(ge=0)


class ReferenceBinding(StrictModel):
    asset_id: str
    role: str
    target: str | None = None
    strength: float | None = Field(default=None, ge=0, le=1)


class CaseAnalysis(StrictModel):
    analysis_id: str
    case_id: str
    visual_style: list[str] = Field(default_factory=list)
    subject_structure: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    lighting: list[str] = Field(default_factory=list)
    color_language: list[str] = Field(default_factory=list)
    shot_structure: dict[str, Any] = Field(default_factory=dict)
    shot_count: int = 0
    average_shot_duration: float = 0
    camera_language: list[str] = Field(default_factory=list)
    motion_language: list[str] = Field(default_factory=list)
    action_structure: list[dict[str, Any]] = Field(default_factory=list)
    temporal_structure: TemporalComplexity
    audio_structure: dict[str, Any] = Field(default_factory=dict)
    transition_structure: dict[str, Any] = Field(default_factory=dict)
    consistency_requirements: list[str] = Field(default_factory=list)
    prompt_features: PromptStructure = Field(default_factory=PromptStructure)
    observed_strengths: list[str] = Field(default_factory=list)
    observed_failures: list[str] = Field(default_factory=list)
    case_shots: list[CaseShot] = Field(default_factory=list)
    reference_bindings: list[ReferenceBinding] = Field(default_factory=list)
    analyzer_version: str = "case-analysis-v1"
    source_analysis_id: str | None = None


_CAMERA_TERMS = ("pan", "tilt", "push", "pull", "dolly", "orbit", "track", "zoom", "handheld", "camera")
_ACTION_TERMS = ("pick", "take", "hold", "touch", "walk", "run", "turn", "open", "close", "look", "speak", "挥", "拿", "触碰", "走", "跑", "转身")
_TEMPORAL_TERMS = ("then", "after", "before", "while", "接着", "然后", "之后", "之前", "同时")


def _terms(prompt: str, vocabulary: tuple[str, ...]) -> list[str]:
    lowered = prompt.lower()
    return [term for term in vocabulary if term in lowered]


def parse_prompt_structure(prompt: str | None, bindings: list[AssetRef] | None = None) -> PromptStructure:
    text = (prompt or "").strip()
    actions = _terms(text, _ACTION_TERMS)
    camera = _terms(text, _CAMERA_TERMS)
    temporal = _terms(text, _TEMPORAL_TERMS)
    clauses = [part.strip() for part in re.split(r"[,;。.!！？]", text) if part.strip()]
    return PromptStructure(
        subject=clauses[:1],
        environment=clauses[1:2],
        visual_style=[],
        composition=[],
        action=actions,
        camera=camera,
        temporal_sequence=temporal,
        lighting=[],
        audio=[],
        constraints=[],
        negative_constraints=[],
        instruction_count=len(clauses),
        action_count=len(actions),
        camera_instruction_count=len(camera),
        temporal_event_count=len(temporal),
        reference_binding_count=len(bindings or []),
    )


def temporal_complexity(
    *, duration_ms: int, prompt: PromptStructure, shot_count: int = 0
) -> TemporalComplexity:
    distinct_actions = prompt.action_count
    camera_events = prompt.camera_instruction_count
    subject_state_changes = max(0, prompt.temporal_event_count + distinct_actions - 1)
    scene_state_changes = max(0, shot_count - 1)
    score = float(distinct_actions + camera_events + subject_state_changes + scene_state_changes)
    return TemporalComplexity(
        duration_s=duration_ms / 1000,
        distinct_actions=distinct_actions,
        camera_events=camera_events,
        subject_state_changes=subject_state_changes,
        scene_state_changes=scene_state_changes,
        complexity_score=score,
    )


def _case_shots(analysis: ReelAnalysis) -> list[CaseShot]:
    result: list[CaseShot] = []
    for index, shot in enumerate(analysis.shots, start=1):
        result.append(
            CaseShot(
                shot_index=index,
                start_ms=shot.start_ms,
                end_ms=shot.end_ms,
                camera_motion=shot.semantic.camera_motion.value,
            )
        )
    return result


def analyze_case(case: VideoCase, reel: ReelAnalysis) -> CaseAnalysis:
    prompt = parse_prompt_structure(case.original_prompt, case.reference_assets)
    complexity = temporal_complexity(
        duration_ms=reel.video_probe.duration_ms,
        prompt=prompt,
        shot_count=len(reel.shots),
    )
    return CaseAnalysis(
        analysis_id=f"case-analysis:{uuid.uuid4().hex}",
        case_id=case.id,
        shot_count=len(reel.shots),
        average_shot_duration=reel.statistics.average_shot_duration_ms,
        shot_structure={"shot_count": len(reel.shots), "cuts_per_minute": reel.statistics.cuts_per_minute},
        camera_language=list(reel.statistics.camera_motion_distribution),
        motion_language=list(reel.statistics.motion_distribution),
        temporal_structure=complexity,
        prompt_features=prompt,
        case_shots=_case_shots(reel),
        reference_bindings=[
            ReferenceBinding(
                asset_id=item.asset_id,
                role=item.role,
                target=item.target,
                strength=item.strength,
            )
            for item in case.reference_assets
        ],
        observed_strengths=["machine_timestamps", "machine_motion"] if reel.quality_report.status.value != "FAIL" else [],
        observed_failures=[finding.code for finding in reel.quality_report.findings if finding.status.value == "FAIL"],
        source_analysis_id=reel.analysis_id,
    )


__all__ = [
    "ActionPhase", "CaseAnalysis", "PromptStructure", "ReferenceBinding",
    "TemporalComplexity", "analyze_case", "parse_prompt_structure", "temporal_complexity",
]
