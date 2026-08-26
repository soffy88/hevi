"""Provider-neutral compilation and explicit unsupported reporting.

P0-A: Constraint Consumption Receipts
- CompilationResult.consumed_constraint_ids → deprecated; use compiled_constraint_ids
- adapter_id / provider_id fields added for receipt generation
- silent_drop tracking preserved but coverage now has granular stages
"""

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
    adapter_id: str = ""
    supported_constraints: set[str] = Field(default_factory=lambda: set(KNOWN_CONSTRAINT_TYPES))
    supports_multi_reference: bool = False


class CompilationResult(BaseModel):
    provider_id: str
    adapter_id: str = ""
    instructions: list[dict[str, Any]] = Field(default_factory=list)
    # DEPRECATED: use compiled_constraint_ids
    consumed_constraint_ids: list[str] = Field(default_factory=list)
    # P0-A: renamed to clarify this is COMPILED stage, not adapter/provider consumed
    compiled_constraint_ids: list[str] = Field(default_factory=list)
    unsupported: list[Constraint] = Field(default_factory=list)
    silent_drops: list[str] = Field(default_factory=list)

    @property
    def constraint_ids(self) -> list[str]:
        """Primary accessor for constraint IDs that were compiled (not consumed)."""
        return self.compiled_constraint_ids if self.compiled_constraint_ids else self.consumed_constraint_ids


class CompilationReceipt(BaseModel):
    """Result of compiling a constraint graph into instructions.

    This is a COMPILED-stage receipt only. Actual provider consumption happens
    when the adapter maps constraints to request payloads (ADAPTER_CONSUMED)
    and the request is submitted (PROVIDER_SUBMITTED).
    """
    provider_id: str
    adapter_id: str
    compiled_instructions: list[dict[str, Any]]
    compiled_constraint_ids: list[str]
    unsupported_constraint_ids: list[str]


def compile_graph(
    graph: ConstraintGraph,
    capabilities: ProviderCapabilities,
) -> CompilationResult:
    result = CompilationResult(
        provider_id=capabilities.provider_id,
        adapter_id=capabilities.adapter_id,
    )
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
        # P0-A: compiled_constraint_ids is the canonical name now
        result.compiled_constraint_ids.append(constraint.id)
        # Deprecated: mirrored for backward compatibility for one release
        result.consumed_constraint_ids.append(constraint.id)

    known_ids = set(result.compiled_constraint_ids)
    known_ids.update(item.id for item in result.unsupported)
    result.silent_drops = [item.id for item in graph.constraints if item.id not in known_ids]

    # P0-A: Update coverage metrics with granular stages
    # Only compiled/adapter_consumed/provider_submitted are set here
    # adapter_consumed/provider_submitted require adapter submission
    graph.coverage.compiled_constraints = len(result.instructions) + len(result.unsupported)
    graph.coverage.silent_drops = len(result.silent_drops)
    graph.coverage.unsupported_constraints = len(result.unsupported)
    # Note: consumed_constraints is deprecated, keep for compat
    graph.coverage.consumed_constraints = result.compiled_constraints
    return result


__all__ = [
    "KNOWN_CONSTRAINT_TYPES",
    "CompilationResult",
    "CompilationReceipt",
    "ProviderCapabilities",
    "compile_graph",
]