"""Deterministic delivery verdicts and scoped repair suggestions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from hevi.production.artifacts import ArtifactManifest

from .compiler import CompilationResult
from .models import ConstraintGraph


class ConstraintViolation(BaseModel):
    constraint_id: str | None = None
    type: str
    scope: str = ""
    severity: Literal["critical", "required", "advisory"] = "required"
    reason: str


class RepairAction(BaseModel):
    action: Literal["regenerate_shot", "redub_shot", "recompile"]
    scope: str
    constraint_ids: list[str] = Field(default_factory=list)
    preserve: list[str] = Field(default_factory=list)


class ConstraintVerdict(BaseModel):
    passed: bool
    score: float = 0.0
    violations: list[ConstraintViolation] = Field(default_factory=list)
    repair_actions: list[RepairAction] = Field(default_factory=list)


def verify_delivery(
    graph: ConstraintGraph,
    compilation: CompilationResult,
    *,
    artifacts: ArtifactManifest | None = None,
) -> ConstraintVerdict:
    violations: list[ConstraintViolation] = []
    repair_groups: dict[tuple[str, str], RepairAction] = {}
    unsupported = {item.id: item for item in compilation.unsupported}
    for constraint in graph.constraints:
        reason: str | None = None
        if constraint.id in unsupported:
            reason = f"provider does not support {constraint.type}"
        elif constraint.id in compilation.silent_drops:
            reason = "constraint was silently dropped during compilation"
        if reason is None:
            continue
        violation = ConstraintViolation(
            constraint_id=constraint.id,
            type=constraint.type,
            scope=constraint.scope,
            severity=constraint.severity,
            reason=reason,
        )
        violations.append(violation)
        if constraint.severity != "advisory":
            action_type: Literal["regenerate_shot", "redub_shot", "recompile"] = (
                "redub_shot" if constraint.type == "dialogue_sync" else "regenerate_shot"
            )
            preserve = ["identity", "wardrobe"] if action_type == "regenerate_shot" else []
            key = (action_type, constraint.scope.split(":")[0])
            action = repair_groups.setdefault(
                key,
                RepairAction(action=action_type, scope=constraint.scope.split(":")[0]),
            )
            action.constraint_ids.append(constraint.id)
            action.preserve = sorted(set(action.preserve + preserve))

    if artifacts is not None:
        violations.extend(
            ConstraintViolation(
                type="artifact_integrity",
                scope=artifact_ref,
                severity="critical",
                reason="artifact is missing or its sha256 does not match",
            )
            for artifact_ref in artifacts.verify_integrity()
        )

    total = len(graph.constraints)
    score = 1.0 if total == 0 else len(compilation.consumed_constraint_ids) / total
    return ConstraintVerdict(
        passed=not any(item.severity in {"critical", "required"} for item in violations),
        score=max(0.0, min(1.0, score)),
        violations=violations,
        repair_actions=list(repair_groups.values()),
    )


__all__ = [
    "ConstraintVerdict",
    "ConstraintViolation",
    "RepairAction",
    "verify_delivery",
]
