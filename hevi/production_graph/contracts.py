"""Typed production commands and deterministic execution-plan contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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


class ExecutionNode(BaseModel):
    node_key: str
    op_type: str
    capability: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    state: Literal["pending", "queued", "running", "completed", "failed"] = "pending"


class ExecutionPlan(BaseModel):
    production_id: UUID
    revision_id: UUID
    plan_version: int = 1
    nodes: list[ExecutionNode] = Field(default_factory=list)

    def validate_dag(self) -> None:
        known = {node.node_key for node in self.nodes}
        if any(dep not in known for node in self.nodes for dep in node.dependencies):
            raise ValueError("execution plan references an unknown dependency")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("execution plan contains a dependency cycle")
            if key in visited:
                return
            visiting.add(key)
            node = next(item for item in self.nodes if item.node_key == key)
            for dep in node.dependencies:
                visit(dep)
            visiting.remove(key)
            visited.add(key)

        for node in self.nodes:
            visit(node.node_key)


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
