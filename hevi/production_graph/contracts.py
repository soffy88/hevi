"""Compatibility exports for production commands and execution plans.

The execution classes used to live in this module.  They now live in the
canonical production domain and are re-exported here so RC6 callers keep
working without maintaining a second execution-plan model.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .domain import ExecutionNode, ExecutionPlan


def inputs_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


class ProductionCommand(BaseModel):
    decision_id: UUID = Field(default_factory=uuid4)
    production_id: UUID
    revision_id: UUID
    inputs_hash: str
    idempotency_key: str
    expected_cost_usd: float = Field(default=0.0, ge=0.0)
    expected_gain: float = Field(default=0.0, ge=0.0)
    rollback: str | None = None
    schema_version: int = 1
    prompt_version: str | None = None


class PlanDecision(ProductionCommand):
    command_type: Literal["plan_decision"] = "plan_decision"
    operation: str
    reason: str


class ToolCall(ProductionCommand):
    command_type: Literal["tool_call"] = "tool_call"
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConstraintChange(ProductionCommand):
    command_type: Literal["constraint_change"] = "constraint_change"
    constraint_id: str
    action: Literal["add", "update", "remove"]
    payload: dict[str, Any] = Field(default_factory=dict)


class RepairDecision(ProductionCommand):
    command_type: Literal["repair_decision"] = "repair_decision"
    scope: str
    action: str
    reason: str


__all__ = [
    "ConstraintChange",
    "ExecutionNode",
    "ExecutionPlan",
    "PlanDecision",
    "ProductionCommand",
    "RepairDecision",
    "ToolCall",
    "inputs_hash",
]
