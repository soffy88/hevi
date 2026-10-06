"""HEVI P6.1 — Narrative grammar model.

A ``NarrativeGrammar`` is a reusable, versioned definition of a narrative
*shape*: which canonical node types appear, in what order, and what constraints
bound them. It is the first P6 grammar with real behaviour.

Relationship to P6.0
--------------------
P6.0 shipped ``hevi.production.p6.schema.NarrativeGrammar``, a *profile-side
declaration* (``mode`` + ``nodes`` + ``arc_constraints``). That type says which
narrative shape a product profile prefers. This module ships a *registry-side
definition* (``id`` + ``version`` + ``name`` + ordered nodes + transitions +
constraints) that a profile then references by id.

They are different concerns and both are legitimate:

    P6.0  profile.NarrativeGrammar   "this product wants an explanatory arc"
    P6.1  narrative.NarrativeGrammar "here is what an explanatory arc is"

The profile declares intent; the registry holds the shared definition. They live
in different modules and neither shadows the other.

Not an authority
----------------
P6.1 does not own story structure. ``hevi.narrative.models.StoryBeat`` and
``hevi.narrative.continuity.ContinuityEngine`` remain canonical, and node
ordering here is *declared intent* that the existing runtime resolves. There is
no second narrative engine and no second beat model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p6.schema import ProductConstraint


class NarrativeNodeType(StrEnum):
    """Canonical narrative node types.

    Closed vocabulary. A node type is a *narrative function*, not a product
    marker, so nothing here may encode which product is being made. Adding
    ``COMMERCIAL_HOOK`` or ``HISTORY_SCENE`` would mean the vocabulary had
    started branching on product type, which is precisely what this layer
    exists to prevent. ``test_no_product_specific_node_type`` enforces it.

    ``DEMONSTRATION``, ``INTERPRETATION``, ``PATTERN_INTERRUPT`` and ``PAYOFF``
    are general narrative functions used by more than one product family.
    ``PATTERN_INTERRUPT`` in particular is a short-form *device*, not a
    short-form-only runtime branch: the same node describes breaking an
    established pattern in any length.
    """

    HOOK = "HOOK"
    CONTEXT = "CONTEXT"
    SETUP = "SETUP"
    DEVELOPMENT = "DEVELOPMENT"
    EVIDENCE = "EVIDENCE"
    EXPLANATION = "EXPLANATION"
    DEMONSTRATION = "DEMONSTRATION"
    INTERPRETATION = "INTERPRETATION"
    CONFLICT = "CONFLICT"
    TURNING_POINT = "TURNING_POINT"
    RESOLUTION = "RESOLUTION"
    PATTERN_INTERRUPT = "PATTERN_INTERRUPT"
    PAYOFF = "PAYOFF"
    CONCLUSION = "CONCLUSION"
    CTA = "CTA"


#: Node types that may not open a grammar. A narrative that starts on its
#: conclusion or call to action has no shape; this is checked at construction.
_NON_OPENING_NODE_TYPES: frozenset[NarrativeNodeType] = frozenset(
    {
        NarrativeNodeType.RESOLUTION,
        NarrativeNodeType.CONCLUSION,
        NarrativeNodeType.CTA,
    }
)


@dataclass(frozen=True)
class NarrativeNode:
    """One node in a grammar.

    ``id`` is grammar-local and unique within the grammar. ``type`` is drawn from
    the closed :class:`NarrativeNodeType` vocabulary. ``required`` marks a node
    the grammar cannot compile without; ``optional`` nodes are emitted only when
    the profile asks for them. ``order`` is the sort key, and must produce a
    total, unambiguous sequence — a grammar with two nodes at the same order is
    ambiguous and is rejected.
    """

    id: str
    type: NarrativeNodeType
    required: bool = True
    optional: bool = False
    order: int = 0
    constraints: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("NARRATIVE_NODE_WITHOUT_ID:id required")
        if not isinstance(self.type, NarrativeNodeType):
            raise ValueError(
                f"UNKNOWN_NARRATIVE_NODE_TYPE:{self.type!r}; the vocabulary is closed"
            )
        if self.required and self.optional:
            raise ValueError(
                f"CONTRADICTORY_NODE_FLAGS:{self.id} cannot be both required and optional"
            )
        if self.order < 0:
            raise ValueError(f"NEGATIVE_NODE_ORDER:{self.id}={self.order}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "required": self.required,
            "optional": self.optional,
            "order": self.order,
            "constraints": [c.to_dict() for c in self.constraints],
        }


@dataclass(frozen=True)
class NarrativeTransition:
    """A declared transition between two nodes.

    Declares that ``from_node`` may be followed by ``to_node``. Transitions are
    advisory structure for the existing edit authority; P6.1 never executes a
    cut.
    """

    from_node: str
    to_node: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.from_node or not self.to_node:
            raise ValueError("INCOMPLETE_NARRATIVE_TRANSITION:both nodes required")
        if self.from_node == self.to_node:
            raise ValueError(
                f"SELF_TRANSITION:{self.from_node} a node cannot follow itself"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NarrativeGrammar:
    """A reusable, versioned narrative shape.

    Immutable and content-hashed. Two grammars with the same id and version but
    different content cannot coexist: the registry rejects the second.
    """

    id: str
    version: str
    name: str
    description: str
    nodes: tuple[NarrativeNode, ...]
    transitions: tuple[NarrativeTransition, ...] = ()
    constraints: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("NARRATIVE_GRAMMAR_WITHOUT_ID:id required")
        if not self.version:
            raise ValueError(f"NARRATIVE_GRAMMAR_WITHOUT_VERSION:{self.id}")
        if not self.name:
            raise ValueError(f"NARRATIVE_GRAMMAR_WITHOUT_NAME:{self.id}")
        if not self.nodes:
            raise ValueError(f"NARRATIVE_GRAMMAR_WITHOUT_NODES:{self.id}")

        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"DUPLICATE_NARRATIVE_NODE_ID:{self.id}:{','.join(dupes)}")

        orders = [n.order for n in self.nodes]
        if len(set(orders)) != len(orders):
            raise ValueError(
                f"AMBIGUOUS_NODE_ORDER:{self.id} two nodes share an order; the "
                "sequence would not be deterministic"
            )

        if self.nodes[0].type in _NON_OPENING_NODE_TYPES:
            raise ValueError(
                f"INVALID_OPENING_NODE:{self.id} may not open with "
                f"{self.nodes[0].type.value}"
            )

        if not any(n.required for n in self.nodes):
            raise ValueError(
                f"NARRATIVE_GRAMMAR_WITHOUT_REQUIRED_NODE:{self.id} every node is optional"
            )

        known = set(ids)
        for t in self.transitions:
            for endpoint in (t.from_node, t.to_node):
                if endpoint not in known:
                    raise ValueError(
                        f"DANGLING_TRANSITION:{self.id}:{endpoint} is not a node "
                        "in this grammar"
                    )

    # ── Access ──────────────────────────────────────────────────────────

    def node(self, node_id: str) -> NarrativeNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def ordered_nodes(self) -> tuple[NarrativeNode, ...]:
        """Nodes in declared order. Deterministic: order is already unique."""
        return tuple(sorted(self.nodes, key=lambda n: n.order))

    def sequence(self) -> tuple[str, ...]:
        """The node-type sequence, for comparison and hashing."""
        return tuple(n.type.value for n in self.ordered_nodes())

    def required_node_ids(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.ordered_nodes() if n.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.ordered_nodes()],
            "transitions": [t.to_dict() for t in self.transitions],
            "constraints": [c.to_dict() for c in self.constraints],
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def qualified_id(self) -> str:
        return f"{self.id}@v{self.version}"


__all__ = [
    "NarrativeGrammar",
    "NarrativeNode",
    "NarrativeNodeType",
    "NarrativeTransition",
]
