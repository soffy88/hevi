"""Evidence-gated pattern and template projections.

Patterns are proposals.  They cannot mutate the Studio catalog or become a
production route without an explicit qualification/promotion decision.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any

from pydantic import Field

from .case_analysis import CaseAnalysis
from .case_models import VideoCase
from .models import StrictModel
from .reproduction import CaseReproduction


class PatternCategory(StrEnum):
    PROMPT = "prompt"
    CAMERA = "camera"
    ACTION = "action"
    MOTION = "motion"
    CONTINUITY = "continuity"
    IDENTITY = "identity"
    STYLE = "style"
    EDITING = "editing"
    AUDIO = "audio"
    PROVIDER = "provider"


class PatternStatus(StrEnum):
    CANDIDATE = "candidate"
    OBSERVED = "observed"
    QUALIFIED = "qualified"
    PROMOTED = "promoted"
    DEPRECATED = "deprecated"


class PatternEvidence(StrictModel):
    case_id: str
    reproduction_id: str
    verdict_status: str
    evidence_refs: list[str] = Field(default_factory=list)
    is_positive: bool
    reason_codes: list[str] = Field(default_factory=list)


class VideoPattern(StrictModel):
    id: str
    name: str
    category: PatternCategory
    evidence_case_ids: list[str] = Field(default_factory=list)
    evidence_reproduction_ids: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    structure: dict[str, Any] = Field(default_factory=dict)
    expected_effect: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    positive_evidence_count: int = 0
    negative_evidence_count: int = 0
    evidence: list[PatternEvidence] = Field(default_factory=list)
    status: PatternStatus = PatternStatus.CANDIDATE


class PromptTemplate(StrictModel):
    id: str
    name: str
    required_slots: list[str] = Field(default_factory=list)
    optional_slots: list[str] = Field(default_factory=list)
    structure: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    supported_modes: list[str] = Field(default_factory=list)
    supported_providers: list[str] = Field(default_factory=list)
    source_pattern_ids: list[str] = Field(default_factory=list)
    qualification_status: PatternStatus = PatternStatus.CANDIDATE


def _verdict_passed(reproduction: CaseReproduction) -> bool:
    status = str(reproduction.verdict.get("status") or "").upper()
    return status in {"PASS", "PASSED", "COMPLETED"}


def extract_pattern_candidate(
    *,
    case: VideoCase,
    analysis: CaseAnalysis,
    reproduction: CaseReproduction,
    category: PatternCategory = PatternCategory.ACTION,
) -> VideoPattern:
    positive = _verdict_passed(reproduction)
    evidence = PatternEvidence(
        case_id=case.id,
        reproduction_id=reproduction.id,
        verdict_status=str(reproduction.verdict.get("status") or "UNKNOWN"),
        evidence_refs=list(reproduction.verdict.get("evidence_refs") or []),
        is_positive=positive,
        reason_codes=list(reproduction.verdict.get("reason_codes") or []),
    )
    signature = {
        "category": category.value,
        "complexity": analysis.temporal_structure.model_dump(mode="json"),
        "prompt": analysis.prompt_features.model_dump(mode="json"),
    }
    digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:16]
    return VideoPattern(
        id=f"pattern:{digest}",
        name=f"{category.value}:{digest}",
        category=category,
        evidence_case_ids=[case.id],
        evidence_reproduction_ids=[reproduction.id],
        conditions={"temporal_complexity": analysis.temporal_structure.model_dump(mode="json")},
        structure={"prompt": analysis.prompt_features.model_dump(mode="json")},
        expected_effect="observed verdict outcome; requires qualification before routing",
        confidence=1.0 if positive else 0.0,
        positive_evidence_count=int(positive),
        negative_evidence_count=int(not positive),
        evidence=[evidence],
    )


def merge_pattern_evidence(pattern: VideoPattern, evidence: PatternEvidence) -> VideoPattern:
    if evidence.reproduction_id in pattern.evidence_reproduction_ids:
        return pattern
    pattern.evidence.append(evidence)
    pattern.evidence_case_ids = sorted({*pattern.evidence_case_ids, evidence.case_id})
    pattern.evidence_reproduction_ids.append(evidence.reproduction_id)
    if evidence.is_positive:
        pattern.positive_evidence_count += 1
    else:
        pattern.negative_evidence_count += 1
    total = pattern.positive_evidence_count + pattern.negative_evidence_count
    pattern.confidence = pattern.positive_evidence_count / total if total else 0
    if total >= 3:
        pattern.status = PatternStatus.OBSERVED
    if total >= 5 and len({item.case_id for item in pattern.evidence}) >= 2:
        pattern.status = PatternStatus.QUALIFIED
    return pattern


def distill_prompt_template(pattern: VideoPattern, *, name: str) -> PromptTemplate:
    return PromptTemplate(
        id=f"template:{uuid.uuid4().hex}",
        name=name,
        required_slots=["subject_state", "action"],
        optional_slots=["camera", "environment"],
        structure=pattern.structure,
        constraints=["preserve observed reference bindings", "do not infer author prompt"],
        source_pattern_ids=[pattern.id],
    )


def qualify_template(template: PromptTemplate, *, passed: bool) -> PromptTemplate:
    if passed:
        template.qualification_status = PatternStatus.QUALIFIED
    return template


def promote_template(template: PromptTemplate, *, explicit_approval: bool) -> PromptTemplate:
    if not explicit_approval or template.qualification_status != PatternStatus.QUALIFIED:
        raise ValueError("TEMPLATE_PROMOTION_REQUIRES_EXPLICIT_APPROVAL_AND_QUALIFICATION")
    template.qualification_status = PatternStatus.PROMOTED
    return template


__all__ = [
    "PatternCategory", "PatternEvidence", "PatternStatus", "PromptTemplate", "VideoPattern",
    "distill_prompt_template", "extract_pattern_candidate", "merge_pattern_evidence",
    "promote_template", "qualify_template",
]
