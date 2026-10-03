"""P10b direction content contracts (Brief/Thesis/Benchmark/Treatment).

Frozen dataclasses + validate(). No writes to Canon/Style/Asset/Provider;
no imports of those authorities (locked by test).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from hevi.creative.direction_content.errors import ContentValidationError

CHECK_CLASSES = ("D", "M", "H")


def content_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                   default=_default).encode()
    ).hexdigest()


def _default(value: object) -> object:
    import dataclasses

    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)  # type: ignore[arg-type]
    if isinstance(value, tuple):
        return list(value)
    return str(value)


# ── Brief ──


@dataclass(frozen=True)
class HardRequirement:
    id: str
    statement: str
    assertion: dict[str, object] = field(default_factory=dict)
    check_class: str = "H"


@dataclass(frozen=True)
class CreativeBrief:
    subject: str
    objective: str
    audience: str
    duration_target: str = ""
    duration_target_ms: int = 0
    desired_effect: str = ""
    emotional_target: str = ""
    platform_constraints: tuple[str, ...] = ()
    brand_constraints: tuple[str, ...] = ()
    factual_constraints: tuple[str, ...] = ()
    hard_requirements: tuple[HardRequirement, ...] = ()
    creative_preferences: tuple[str, ...] = ()
    forbidden_elements: tuple[str, ...] = ()
    source_type: str = "user"
    source_reference: str = ""

    def validate(self) -> None:
        if not self.subject or not self.objective or not self.audience:
            raise ContentValidationError("brief subject/objective/audience required",
                                         code="BRIEF_INCOMPLETE")
        for hr in self.hard_requirements:
            if hr.check_class not in CHECK_CLASSES:
                raise ContentValidationError(f"hard requirement {hr.id}: bad check_class",
                                             code="BRIEF_BAD_CLASS")
            if not hr.assertion and hr.check_class != "H":
                raise ContentValidationError(
                    f"hard requirement {hr.id}: no assertion must be class H",
                    code="HARDREQ_UNASSERTED")

    def touches_hard_requirement(self) -> bool:
        return bool(self.hard_requirements)


# ── Thesis ──


@dataclass(frozen=True)
class FactualClaim:
    text: str
    canon_ref: str = ""


@dataclass(frozen=True)
class CreativeThesis:
    logline: str
    central_question: str
    emotional_arc: str
    audience_effect: str
    thematic_focus: str = ""
    creative_strategy: str = ""
    factual_claims: tuple[FactualClaim, ...] = ()

    def validate(self) -> None:
        if not (self.logline and self.central_question and self.emotional_arc and self.audience_effect):
            raise ContentValidationError("thesis four-part required", code="THESIS_INCOMPLETE")
        for claim in self.factual_claims:
            if not claim.canon_ref:
                raise ContentValidationError(f"factual claim without canon_ref: {claim.text[:40]}",
                                             code="THESIS_FACT_UNPINNED")


# ── Benchmark ──


@dataclass(frozen=True)
class ExtractedPrinciple:
    id: str
    statement: str
    dimension: str = ""
    abstraction_level: str = ""


@dataclass(frozen=True)
class BenchmarkReference:
    id: str
    title: str
    creator: str = ""
    uri: str = ""
    retrieved_at: str = ""
    reference_hash: str = ""
    extraction_method: str = "human"
    extraction_actor: str = ""
    transfer_mode: str = "principle_only"
    principles: tuple[ExtractedPrinciple, ...] = ()
    avoid: tuple[str, ...] = ()
    relevance: str = ""
    ip_note: str = ""

    def validate(self) -> None:
        if self.transfer_mode != "principle_only":
            raise ContentValidationError(f"benchmark {self.id}: only principle_only in P10b",
                                         code="BENCHMARK_TRANSFER_FORBIDDEN")
        if not self.principles:
            raise ContentValidationError(f"benchmark {self.id}: principles required",
                                         code="BENCHMARK_EMPTY_PRINCIPLES")
        if not (self.uri and self.retrieved_at and self.reference_hash):
            raise ContentValidationError(f"benchmark {self.id}: reference_access incomplete",
                                         code="BENCHMARK_ACCESS_INCOMPLETE")


@dataclass(frozen=True)
class BenchmarkSet:
    references: tuple[BenchmarkReference, ...] = ()

    def validate(self) -> None:
        if not self.references:
            raise ContentValidationError("benchmark set empty", code="BENCHMARK_EMPTY")
        for ref in self.references:
            ref.validate()

    def principle_ids(self) -> set[str]:
        return {p.id for r in self.references for p in r.principles}


# ── Treatment ──


@dataclass(frozen=True)
class TreatmentAlternative:
    id: str
    structure: str
    rationale: str = ""


@dataclass(frozen=True)
class Treatment:
    thesis_ref: str
    structure: str
    opening: str = ""
    setup: str = ""
    development: str = ""
    turning_point: str = ""
    climax: str = ""
    resolution: str = ""
    ending: str = ""
    pacing: str = ""
    emotional_arc: str = ""
    visual_strategy: str = ""
    sound_strategy: str = ""
    typography_strategy: str = ""
    signature_moments: tuple[str, ...] = ()
    signature_shots: tuple[str, ...] = ()
    alternatives: tuple[TreatmentAlternative, ...] = ()
    short_form_reason: str = ""  # K<3 时必填
    comparison_criteria: tuple[str, ...] = ()
    comparison_matrix: dict[str, dict[str, str]] = field(default_factory=dict)
    recommended_by_actor: str = ""
    recommended_by_rationale: str = ""
    selected: str = ""
    selected_by_actor: str = ""
    selected_by_rule: str = ""
    selection_rationale: str = ""

    def validate(self) -> None:
        if len(self.alternatives) < 3 and not self.short_form_reason:
            raise ContentValidationError("treatment K<3 requires short_form_reason",
                                         code="TREATMENT_K_INSUFFICIENT")
        if self.comparison_matrix and not self.comparison_criteria:
            raise ContentValidationError("comparison criteria must precede scores",
                                         code="TREATMENT_NO_CRITERIA")
        if not self.selected:
            raise ContentValidationError("treatment selected required", code="TREATMENT_UNSELECTED")
        if self.selected not in {a.id for a in self.alternatives}:
            raise ContentValidationError("selected not in alternatives", code="TREATMENT_BAD_SELECTION")
        if not self.selection_rationale or not self.selected_by_actor:
            raise ContentValidationError("selection rationale + actor required",
                                         code="TREATMENT_NO_RATIONALE")
