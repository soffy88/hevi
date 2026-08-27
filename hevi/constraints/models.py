"""Serializable Constraint Graph contracts.

Constraints are deliberately provider-neutral.  Providers compile them into
prompts, control inputs, reference images, or deterministic checks, while the
graph remains the canonical explanation of what a shot must preserve.

P0-A: Constraint Consumption Receipts
- ConsumptionStage enum: COMPILED, ADAPTER_CONSUMED, PROVIDER_SUBMITTED, PROVIDER_ACKED
- ConstraintConsumptionReceipt: immutable record of actual consumption
- ConstraintMapping: adapter→provider payload mapping with hash for audit
- CoverageReport: renamed consumed→compiled; new adapter/provider/verification coverage
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Constraint(BaseModel):
    id: str
    type: str
    severity: Literal["critical", "required", "advisory"] = "required"
    scope: str
    source_revision_id: str | None = None
    source_path: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on_ids: list[str] = Field(default_factory=list)
    compile_required: bool = True
    verification_required: bool = True
    fallback_policy: Literal["fail", "degrade", "warn"] = "fail"


class ConsumptionStage(StrEnum):
    """Lifecycle stage of a constraint as it flows from derivation to provider."""
    COMPILED = "compiled"
    ADAPTER_CONSUMED = "adapter_consumed"
    PROVIDER_SUBMITTED = "provider_submitted"
    PROVIDER_ACKED = "provider_acked"


class ConstraintMapping(BaseModel):
    """Maps a single constraint to a location in the provider request payload."""
    constraint_id: str
    mapping_type: str  # prompt/reference/control/audio/camera/etc
    mapping_path: str  # e.g. request.image_refs[0], prompt.variables.subject
    payload_hash: str  # sha256(canonical mapped payload) for audit/reproducibility


class ConstraintConsumptionReceipt(BaseModel):
    """Immutable record that a constraint was actually consumed by an adapter/provider.

    Created at three stages:
    1. COMPILED: compiler accepts constraint (legacy compatibility)
    2. ADAPTER_CONSUMED: provider adapter maps constraint to request payload
    3. PROVIDER_SUBMITTED: request sent and accepted by provider
    4. PROVIDER_ACKED: provider returns job/request id
    """
    id: str
    production_id: str
    revision_id: str
    attempt_id: str
    constraint_id: str
    provider_id: str
    adapter_id: str
    stage: ConsumptionStage
    mapping_type: str
    mapping_path: str
    payload_hash: str
    provider_request_id: str | None = None
    created_at: str  # ISO8601 UTC


class CoverageReport(BaseModel):
    """Constraint pipeline coverage metrics (P0-A).

    renamed: consumed_constraints -> compiled_constraints
    new: adapter_consumed_constraints, provider_submitted_constraints, verified_constraints
    """
    expected_fields: int = 0
    derived_constraints: int = 0
    compiled_constraints: int = 0
    adapter_consumed_constraints: int = 0
    provider_submitted_constraints: int = 0
    verified_constraints: int = 0
    unsupported_constraints: int = 0
    silent_drops: int = 0

    @property
    def derivation_rate(self) -> float:
        if self.expected_fields == 0:
            return 1.0
        return self.derived_constraints / self.expected_fields

    @property
    def compilation_rate(self) -> float:
        """Renamed from consumption_rate: compiled / derived"""
        if self.derived_constraints == 0:
            return 1.0
        return self.compiled_constraints / self.derived_constraints

    @property
    def adapter_consumption_rate(self) -> float:
        """adapter_consumed / required_supported"""
        if self.compiled_constraints == 0:
            return 1.0
        return self.adapter_consumed_constraints / self.compiled_constraints

    @property
    def provider_submission_rate(self) -> float:
        """provider_submitted / adapter_consumed"""
        if self.adapter_consumed_constraints == 0:
            return 1.0
        return self.provider_submitted_constraints / self.adapter_consumed_constraints

    @property
    def verification_rate(self) -> float:
        """verified / provider_submitted"""
        if self.provider_submitted_constraints == 0:
            return 1.0
        return self.verified_constraints / self.provider_submitted_constraints

    @property
    def silent_drop_rate(self) -> float:
        if self.derived_constraints == 0:
            return 0.0
        return self.silent_drops / self.derived_constraints

    # DEPRECATED: kept for one-version compatibility
    @property
    def consumption_rate(self) -> float:
        """DEPRECATED: use compilation_rate, adapter_consumption_rate, or provider_submission_rate"""
        return self.compilation_rate


class ConstraintGraph(BaseModel):
    revision_id: str | None = None
    version: int = 1
    constraints: list[Constraint] = Field(default_factory=list)
    coverage: CoverageReport = Field(default_factory=CoverageReport)

    def by_type(self, constraint_type: str) -> list[Constraint]:
        return [item for item in self.constraints if item.type == constraint_type]


__all__ = [
    "Constraint",
    "ConstraintConsumptionReceipt",
    "ConstraintGraph",
    "ConstraintMapping",
    "ConsumptionStage",
    "CoverageReport",
]
