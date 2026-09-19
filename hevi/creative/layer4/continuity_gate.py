"""D3-B: continuity as a production gate (HEVI Layer 4).

The D2 :class:`ContinuityLedger` + :func:`validate_pre_production` become
default production behavior through two canonical paths:

- :func:`record_production_fact` — the ONLY sanctioned writer of new
  continuity facts from production. Accepted sources: explicit user/canon
  input, approved character state, approved scene/shot results, previous
  production artifact metadata. Anything AI-inferred is forced to
  ``provenance="inferred"`` and can never become a hard BLOCK.
- :func:`gate_production_stage` — runs before storyboard approval,
  reference preparation, video generation, and voice generation. PASS
  proceeds; WARN proceeds with the override decision persisted for audit;
  BLOCK refuses paid generation (raises :class:`GateRefusal`).

Failed generations never touch this module, so canonical continuity state
cannot be mutated by a failure. History is append-only (store uses
INSERT OR IGNORE by fact_id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    ContinuityFactRecord,
    ContinuitySeverity,
    PersistentIdentityRegistry,
    ProjectCharacterBinding,
    validate_pre_production,
)


class GateError(ValueError):
    """Refusal with a stable machine code."""


class GateRefusal(GateError):
    """BLOCK verdict on a paid stage: paid generation must not enqueue."""


class ProductionStage(StrEnum):
    STORYBOARD_APPROVAL = "storyboard_approval"
    REFERENCE_PREPARATION = "reference_preparation"
    VIDEO_GENERATION = "video_generation"
    VOICE_GENERATION = "voice_generation"


#: Stages that may bill the owner when enqueued.
PAID_STAGES: tuple[ProductionStage, ...] = (
    ProductionStage.VIDEO_GENERATION,
    ProductionStage.VOICE_GENERATION,
)

#: Fact sources allowed to write canonical (BLOCK-capable) truth.
APPROVED_SOURCES: tuple[str, ...] = (
    "user",
    "canon",
    "approved-character-state",
    "approved-scene-result",
    "approved-shot-result",
    "production-artifact",
)


class FactSource(StrEnum):
    USER_CANON = "user"
    CANON = "canon"
    APPROVED_CHARACTER_STATE = "approved-character-state"
    APPROVED_SCENE_RESULT = "approved-scene-result"
    APPROVED_SHOT_RESULT = "approved-shot-result"
    PRODUCTION_ARTIFACT = "production-artifact"
    INFERRED = "inferred"


class ContinuityDecision(BaseModel):
    """Audited WARN-override record: who proceeded past what warning, when."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    stage: ProductionStage
    verdict: ContinuitySeverity
    warn_codes: tuple[str, ...] = ()
    overridden_by: str = ""
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def record_production_fact(
    *,
    store: IdentityStore,
    registry: PersistentIdentityRegistry,
    owner_id: str,
    identity_id: str,
    category: ContinuityCategory,
    statement: str,
    source: FactSource | str,
    source_artifact_id: str = "",
    episode: str = "",
    scene: str = "",
    shot: str = "",
    revision: str = "",
) -> ContinuityFactRecord:
    """Canonical commit path for new continuity facts (D3-B/B1+B4).

    Verifies the identity belongs to the owner, forces AI-inferred input
    to ``provenance="inferred"`` (never BLOCK-capable), appends to both
    the in-memory ledger and the durable store. Failed generations never
    reach this function, so failures cannot mutate canonical state.
    """
    raw_source = str(source or "").strip().lower()
    provenance = raw_source if raw_source in APPROVED_SOURCES else FactSource.INFERRED.value
    identity = registry.get_identity(identity_id, owner_id=owner_id)
    fact = ContinuityFactRecord(
        fact_id=f"fact-{uuid4().hex[:12]}",
        identity_id=identity.identity_id,
        category=category,
        statement=statement,
        episode=episode,
        scene=scene,
        shot=shot,
        revision=revision,
        source_artifact_id=source_artifact_id,
        provenance=provenance,
    )
    registry.ledger.record(fact)
    store.save_fact(owner_id, fact.model_dump(mode="json"))
    return fact


def gate_production_stage(
    *,
    store: IdentityStore,
    registry: PersistentIdentityRegistry,
    binding: ProjectCharacterBinding,
    owner_id: str,
    stage: ProductionStage,
    planned_appearance_id: str = "default",
    planned_voice_id: str = "",
    planned_location: str = "",
    planned_props: tuple[str, ...] = (),
    planned_statements: tuple[str, ...] = (),
    overridden_by: str = "",
) -> ContinuityDecision:
    """Run continuity validation before a production stage (D3-B/B2+B3).

    - verdict PASS: proceed, decision recorded.
    - verdict WARN: proceed only with ``overridden_by`` set (the human or
      calling system accepting the warnings); the decision is persisted.
    - verdict BLOCK on a paid stage: raise :class:`GateRefusal` — paid
      generation must not enqueue. BLOCK on a non-paid stage also raises:
      a hard contradiction must be fixed, not worked around.
    - UNKNOWN (insufficient data) surfaces as WARN, never fake PASS:
      the validator only returns PASS when every check affirmatively holds.
    """
    verdict = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id=owner_id,
        planned_appearance_id=planned_appearance_id,
        planned_voice_id=planned_voice_id,
        planned_location=planned_location,
        planned_props=planned_props,
        planned_statements=planned_statements,
    )
    if verdict.verdict is ContinuitySeverity.BLOCK:
        codes = ",".join(finding.code for finding in verdict.findings)
        store.save_decision(
            owner_id,
            ContinuityDecision(
                decision_id=f"gate-{uuid4().hex[:12]}",
                binding_id=binding.binding_id,
                stage=stage,
                verdict=ContinuitySeverity.BLOCK,
                warn_codes=tuple(finding.code for finding in verdict.findings),
                overridden_by="",
            ).model_dump(mode="json"),
        )
        raise GateRefusal(f"CONTINUITY_GATE_BLOCKED:{stage.value}:{codes}")
    warn_codes = [finding.code for finding in verdict.findings]
    # B3: insufficient data must not fake PASS. With zero recorded facts,
    # location/prop continuity cannot be affirmatively confirmed.
    known_facts = registry.ledger.facts_for_identity(binding.identity_id)
    if not known_facts and (planned_location or planned_props):
        warn_codes.append("CONTINUITY_DATA_SPARSE")
    effective = (
        ContinuitySeverity.WARN
        if (verdict.verdict is ContinuitySeverity.WARN or "CONTINUITY_DATA_SPARSE" in warn_codes)
        else ContinuitySeverity.PASS
    )
    decision = ContinuityDecision(
        decision_id=f"gate-{uuid4().hex[:12]}",
        binding_id=binding.binding_id,
        stage=stage,
        verdict=effective,
        warn_codes=tuple(warn_codes),
        overridden_by=overridden_by,
    )
    if effective is ContinuitySeverity.WARN and not overridden_by.strip():
        raise GateError("CONTINUITY_GATE_WARN_NEEDS_OVERRIDE")
    store.save_decision(owner_id, decision.model_dump(mode="json"))
    return decision


__all__ = [
    "APPROVED_SOURCES",
    "PAID_STAGES",
    "ContinuityDecision",
    "FactSource",
    "GateError",
    "GateRefusal",
    "ProductionStage",
    "gate_production_stage",
    "record_production_fact",
]
