"""Serializable Constraint Graph contracts.

Constraints are deliberately provider-neutral.  Providers compile them into
prompts, control inputs, reference images, or deterministic checks, while the
graph remains the canonical explanation of what a shot must preserve.
"""

from __future__ import annotations

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


class CoverageReport(BaseModel):
    expected_fields: int = 0
    derived_constraints: int = 0
    compiled_constraints: int = 0
    consumed_constraints: int = 0
    verified_constraints: int = 0
    unsupported_constraints: int = 0
    silent_drops: int = 0

    @property
    def derivation_rate(self) -> float:
        if self.expected_fields == 0:
            return 1.0
        return self.derived_constraints / self.expected_fields

    @property
    def consumption_rate(self) -> float:
        if self.derived_constraints == 0:
            return 1.0
        return self.consumed_constraints / self.derived_constraints

    @property
    def verification_rate(self) -> float:
        required = self.derived_constraints
        if required == 0:
            return 1.0
        return self.verified_constraints / required


class ConstraintGraph(BaseModel):
    revision_id: str | None = None
    version: int = 1
    constraints: list[Constraint] = Field(default_factory=list)
    coverage: CoverageReport = Field(default_factory=CoverageReport)

    def by_type(self, constraint_type: str) -> list[Constraint]:
        return [item for item in self.constraints if item.type == constraint_type]
