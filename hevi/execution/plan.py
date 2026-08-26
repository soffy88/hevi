"""P0-E: Execution Plan Immutability

ExecutionPlan is now INSERT-ONLY.  Same (production, revision, plan_version) cannot be
ON CONFLICT UPDATE.  Modifications create new plan_version with parent_plan_id.

Plan hash: sha256(canonical(plan_json)) for idempotent retry detection.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ImmutablePlanViolation(Exception):
    """Raised when attempting to modify an existing ExecutionPlan version."""
    pass


class ExecutionPlan(BaseModel):
    """Immutable execution plan for a production/revision.

    Each plan_version is immutable.  To change a plan, create a new version.
    """
    id: str = ""
    production_id: str = ""
    revision_id: str = ""
    plan_version: int = 1
    plan_json: dict[str, Any] = Field(default_factory=dict)
    plan_hash: str = ""  # sha256(canonical(plan_json))
    parent_plan_id: str | None = None  # previous version's id
    created_by_attempt_id: str | None = None  # which attempt created this
    change_reason: Literal["initial", "repair", "replan", "manual_edit"] = "initial"
    created_at: str = ""  # ISO8601 UTC

    @classmethod
    def create(
        cls,
        production_id: str,
        revision_id: str,
        plan_json: dict[str, Any],
        *,
        plan_version: int = 1,
        parent_plan_id: str | None = None,
        created_by_attempt_id: str | None = None,
        change_reason: str = "initial",
    ) -> "ExecutionPlan":
        """Create a new immutable ExecutionPlan."""
        import hashlib
        import json
        canonical = json.dumps(plan_json, sort_keys=True, separators=(",", ":"))
        plan_hash = hashlib.sha256(canonical.encode()).hexdigest()
        return cls(
            id=str(uuid.uuid4()),
            production_id=production_id,
            revision_id=revision_id,
            plan_version=plan_version,
            plan_json=plan_json,
            plan_hash=plan_hash,
            parent_plan_id=parent_plan_id,
            created_by_attempt_id=created_by_attempt_id,
            change_reason=change_reason,  # type: ignore[arg-type]
            created_at=datetime.now().isoformat(),
        )

    @classmethod
    def from_existing(
        cls,
        existing: "ExecutionPlan",
        new_plan_json: dict[str, Any],
        *,
        created_by_attempt_id: str | None = None,
        change_reason: str = "repair",
    ) -> "ExecutionPlan":
        """Create a new version from an existing plan (for repair/replan).

        This is the ONLY way to modify a plan: never update existing in-place.
        """
        return cls.create(
            production_id=existing.production_id,
            revision_id=existing.revision_id,
            plan_json=new_plan_json,
            plan_version=existing.plan_version + 1,
            parent_plan_id=existing.id,
            created_by_attempt_id=created_by_attempt_id,
            change_reason=change_reason,
        )


class RepairPlan(BaseModel):
    """P0-C: DAG-scoped autonomous repair plan.

    Contains:
    - root_nodes: constraints/nodes that failed
    - rerun_nodes: DAG closure of nodes that must be re-executed
    - preserve_artifact_ids: artifacts that remain valid and should not be re-run
    - estimated_cost: budget needed for repair
    - expected_gain: quality improvement expected
    """
    id: str = ""
    production_id: str = ""
    source_attempt_id: str = ""
    source_verdict_id: str = ""
    violated_constraint_ids: list[str] = Field(default_factory=list)
    root_nodes: list[str] = Field(default_factory=list)
    rerun_nodes: list[str] = Field(default_factory=list)
    preserve_artifact_ids: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    expected_gain: float = 0.0
    decision: Literal["execute", "stop", "human_review"] = "stop"
    reason: str = ""
    iteration: int = 0
    created_at: str = ""

    @classmethod
    def create(
        cls,
        production_id: str,
        source_attempt_id: str,
        source_verdict_id: str,
        violated_constraint_ids: list[str],
        root_nodes: list[str],
        rerun_nodes: list[str],
        preserve_artifact_ids: list[str],
        estimated_cost: float,
        expected_gain: float,
        decision: str,
        reason: str,
        iteration: int,
    ) -> "RepairPlan":
        return cls(
            id=str(uuid.uuid4()),
            production_id=production_id,
            source_attempt_id=source_attempt_id,
            source_verdict_id=source_verdict_id,
            violated_constraint_ids=violated_constraint_ids,
            root_nodes=root_nodes,
            rerun_nodes=rerun_nodes,
            preserve_artifact_ids=preserve_artifact_ids,
            estimated_cost=estimated_cost,
            expected_gain=expected_gain,
            decision=decision,  # type: ignore[arg-type]
            reason=reason,
            iteration=iteration,
            created_at=datetime.now().isoformat(),
        )


def compute_dag_closure(
    root_nodes: list[str],
    all_nodes: dict[str, list[str]],  # node_id -> [downstream_node_ids]
    artifact_outputs: dict[str, str],  # node_id -> artifact_id
    changed_inputs: set[str],
) -> tuple[list[str], list[str]]:
    """Compute DAG closure for repair.

    Returns (rerun_nodes, preserve_artifact_ids):
    - rerun_nodes: nodes whose outputs changed or are downstream of changed nodes
    - preserve_artifact_ids: artifacts that remain valid (not in rerun_nodes)

    Algorithm:
    1. Start from root_nodes
    2. Compute downstream closure
    3. Filter: only include nodes whose artifact is invalidated by changed inputs
    4. Preserve: all other artifacts
    """
    # Compute downstream closure from root_nodes
    closure: set[str] = set()
    queue = list(root_nodes)
    while queue:
        node = queue.pop(0)
        if node in closure:
            continue
        closure.add(node)
        for downstream in all_nodes.get(node, []):
            if downstream not in closure:
                queue.append(downstream)

    # Filter: only nodes whose outputs are invalidated
    rerun: list[str] = []
    for node in closure:
        artifact_id = artifact_outputs.get(node)
        if artifact_id is None:
            rerun.append(node)
        elif artifact_id in changed_inputs:
            rerun.append(node)
        else:
            # Artifact is still valid (not invalidated by changed inputs)
            pass

    # Preserve: all artifacts not in rerun
    preserve = [
        artifact_id
        for node, artifact_id in artifact_outputs.items()
        if node not in rerun
    ]

    return rerun, preserve


def decide_repair(
    evaluation_score: float,
    previous_score: float | None,
    iteration: int,
    budget_remaining: float,
    estimated_cost: float,
    max_iterations: int = 2,
    min_gain: float = 0.05,
    convergence_state: str = "fresh",
) -> tuple[bool, str]:
    """Decide whether to repair based on budget, iterations, and convergence.

    Returns (should_repair, stop_reason).
    """
    if evaluation_score >= 0.95:
        return False, "gates_passed"

    if iteration >= max_iterations:
        return False, "max_iterations_reached"

    if budget_remaining < estimated_cost:
        return False, "budget_exhausted"

    if convergence_state in ("oscillating", "diverging"):
        return False, f"convergence_{convergence_state}"

    # Check marginal gain
    if previous_score is not None:
        gain = evaluation_score - previous_score
        if gain < min_gain:
            return False, "marginal_gain_below_threshold"

    return True, ""


__all__ = [
    "ExecutionPlan",
    "ImmutablePlanViolation",
    "RepairPlan",
    "compute_dag_closure",
    "decide_repair",
]