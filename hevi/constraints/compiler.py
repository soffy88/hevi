"""Provider-neutral compilation and explicit unsupported reporting."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .models import Constraint, ConstraintGraph

KNOWN_CONSTRAINT_TYPES = frozenset(
    {
        "identity",
        "wardrobe",
        "scene",
        "eyeline",
        "blocking",
        "camera",
        "dialogue_sync",
        "negative",
        "performance",
        "timing",
        "audio",
        "style",
        "continuity",
        "safety",
        "delivery",
    }
)


class ProviderCapabilities(BaseModel):
    provider_id: str
    supported_constraints: set[str] = Field(default_factory=lambda: set(KNOWN_CONSTRAINT_TYPES))
    supports_multi_reference: bool = False


class CompilationResult(BaseModel):
    provider_id: str
    instructions: list[dict[str, Any]] = Field(default_factory=list)
    consumed_constraint_ids: list[str] = Field(default_factory=list)
    unsupported: list[Constraint] = Field(default_factory=list)
    silent_drops: list[str] = Field(default_factory=list)


def compile_graph(
    graph: ConstraintGraph,
    capabilities: ProviderCapabilities,
) -> CompilationResult:
    result = CompilationResult(provider_id=capabilities.provider_id)
    for constraint in graph.constraints:
        if constraint.type not in capabilities.supported_constraints:
            result.unsupported.append(constraint)
            continue
        # Keep the structured payload intact.  Provider adapters can render it
        # differently without losing the constraint id used by verification.
        result.instructions.append(
            {
                "constraint_id": constraint.id,
                "type": constraint.type,
                "scope": constraint.scope,
                "payload": constraint.payload,
            }
        )
        result.consumed_constraint_ids.append(constraint.id)
    known_ids = set(result.consumed_constraint_ids)
    known_ids.update(item.id for item in result.unsupported)
    result.silent_drops = [item.id for item in graph.constraints if item.id not in known_ids]
    graph.coverage.compiled_constraints = len(result.instructions) + len(result.unsupported)
    graph.coverage.consumed_constraints = len(result.consumed_constraint_ids)
    graph.coverage.unsupported_constraints = len(result.unsupported)
    graph.coverage.silent_drops = len(result.silent_drops)
    return result


__all__ = [
    "KNOWN_CONSTRAINT_TYPES",
    "CompilationResult",
    "ProviderCapabilities",
    "compile_graph",
]
