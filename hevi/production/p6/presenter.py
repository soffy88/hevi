"""HEVI P6.2 — Presenter grammar model.

A ``PresenterGrammar`` declares how a *presenter* performs: which presentation
nodes appear, in what order, and what the presenter must be able to do. It is
the second P6 grammar with real behaviour, and it consumes
:class:`~hevi.production.p6.narrative.compiler.NarrativeIntent` rather than
re-deriving narrative.

Relationship to P6.0 / P6.1
--------------------------
P6.0 shipped ``schema.PresenterGrammar`` — a profile-side *declaration*
(``presenter_id``, ``kind``, delivery and camera policy). This module ships a
registry-side *definition* (``id`` + ordered presenter nodes + presentation,
speaker, visual and audio requirements). Both are legitimate and neither shadows
the other; see ``docs/P6-2-PRESENTER-GRAMMAR.md``.

Vocabulary boundary
-------------------
``PresenterNodeType`` is a *presentation function* vocabulary. It is disjoint from
``NarrativeNodeType`` on purpose: a narrative node says what the story is doing
(``EVIDENCE``, ``TURNING_POINT``), a presenter node says what the presenter is
doing while it happens (``IDENTITY``, ``AUTHORITY``, ``EMOTION``). The two
overlap only where the function genuinely coincides (``HOOK``, ``EXPLANATION``,
``CTA``, ``CONCLUSION``), and that overlap is a vocabulary alignment, not a
second narrative engine.

``CHARACTER`` and ``EVENT`` are part of this vocabulary because a presenter
performing a historical reconstruction *is* the character and *does* narrate
events. They name a presentation function, not a product.

Not an authority
----------------
A presenter grammar declares requirements. It does not select a provider, cast a
voice, drive a camera, or generate a frame. ``hevi.providers``,
``hevi.renderers`` and the P5.1 presenter/voice authorities are untouched and
unimported.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p6.schema import ProductConstraint


class PresenterNodeType(StrEnum):
    """Canonical presenter node types.

    Closed vocabulary, and generic: a node names what the presenter *does*, never
    which product is being made. ``COMMERCIAL_HOOK`` and ``P08_CTA`` are the
    failure modes — a node named after a product means the vocabulary has started
    branching on product identity, which is precisely what this layer exists to
    prevent. ``test_no_product_specific_presenter_node_type`` enforces it.
    """

    INTRO = "INTRO"
    HOOK = "HOOK"
    IDENTITY = "IDENTITY"
    AUTHORITY = "AUTHORITY"
    CONTEXT = "CONTEXT"
    EXPLANATION = "EXPLANATION"
    DEMONSTRATION = "DEMONSTRATION"
    EVIDENCE = "EVIDENCE"
    CHARACTER = "CHARACTER"
    EVENT = "EVENT"
    INTERPRETATION = "INTERPRETATION"
    EMOTION = "EMOTION"
    TRANSITION = "TRANSITION"
    CTA = "CTA"
    CONCLUSION = "CONCLUSION"


#: Node types that may not open a presenter grammar. A performance that starts
#: on its call to action or its conclusion has no shape.
_NON_OPENING_PRESENTER_NODES: frozenset[PresenterNodeType] = frozenset(
    {
        PresenterNodeType.CTA,
        PresenterNodeType.CONCLUSION,
        PresenterNodeType.TRANSITION,
    }
)


@dataclass(frozen=True)
class PresenterNode:
    """One node in a presenter grammar.

    ``purpose`` states why the presenter is doing this, in semantic terms — it is
    what a later stage reads to decide how hard the performance works. ``order``
    must be unique within the grammar so the sequence is deterministic.
    """

    id: str
    type: PresenterNodeType
    purpose: str = ""
    required: bool = True
    order: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("PRESENTER_NODE_WITHOUT_ID:id required")
        if not isinstance(self.type, PresenterNodeType):
            raise ValueError(
                f"UNKNOWN_PRESENTER_NODE_TYPE:{self.type!r}; the vocabulary is closed"
            )
        if not self.purpose:
            raise ValueError(f"PRESENTER_NODE_WITHOUT_PURPOSE:{self.id}")
        if self.order < 0:
            raise ValueError(f"NEGATIVE_PRESENTER_NODE_ORDER:{self.id}={self.order}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PresenterRequirements:
    """What the presenter must be able to do, per channel.

    Declarative and channel-separated. ``speaker_requirements`` is about who
    speaks and how credibly; ``visual_requirements`` is about what must be
    present on screen; ``audio_requirements`` is about the voice. None of them
    names a provider, a model, or a renderer.
    """

    speaker_requirements: tuple[ProductConstraint, ...] = ()
    visual_requirements: tuple[ProductConstraint, ...] = ()
    audio_requirements: tuple[ProductConstraint, ...] = ()
    presentation_style: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "presentation_style": self.presentation_style,
            "speaker_requirements": [c.to_dict() for c in self.speaker_requirements],
            "visual_requirements": [c.to_dict() for c in self.visual_requirements],
            "audio_requirements": [c.to_dict() for c in self.audio_requirements],
        }

    @property
    def is_empty(self) -> bool:
        return not (
            self.speaker_requirements
            or self.visual_requirements
            or self.audio_requirements
            or self.presentation_style
        )


@dataclass(frozen=True)
class PresenterGrammar:
    """A reusable, versioned presenter performance shape.

    Immutable and content-hashed. A grammar whose required nodes were all
    removed cannot be constructed, so a compiled intent can never be an empty
    list.
    """

    id: str
    version: str
    name: str
    description: str
    nodes: tuple[PresenterNode, ...]
    requirements: PresenterRequirements = PresenterRequirements()
    constraints: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("PRESENTER_GRAMMAR_WITHOUT_ID:id required")
        if not self.version:
            raise ValueError(f"PRESENTER_GRAMMAR_WITHOUT_VERSION:{self.id}")
        if not self.name:
            raise ValueError(f"PRESENTER_GRAMMAR_WITHOUT_NAME:{self.id}")
        if not self.nodes:
            raise ValueError(f"PRESENTER_GRAMMAR_WITHOUT_NODES:{self.id}")

        ids = [n.id for n in self.nodes]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"DUPLICATE_PRESENTER_NODE_ID:{self.id}:{','.join(dupes)}")

        orders = [n.order for n in self.nodes]
        if len(set(orders)) != len(orders):
            raise ValueError(
                f"AMBIGUOUS_PRESENTER_NODE_ORDER:{self.id} two nodes share an order; "
                "the sequence would not be deterministic"
            )

        if self.nodes[0].type in _NON_OPENING_PRESENTER_NODES:
            raise ValueError(
                f"INVALID_PRESENTER_OPENING_NODE:{self.id} may not open with "
                f"{self.nodes[0].type.value}"
            )

        if not any(n.required for n in self.nodes):
            raise ValueError(
                f"PRESENTER_GRAMMAR_WITHOUT_REQUIRED_NODE:{self.id} every node is optional"
            )

    def node(self, node_id: str) -> PresenterNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def ordered_nodes(self) -> tuple[PresenterNode, ...]:
        return tuple(sorted(self.nodes, key=lambda n: n.order))

    def sequence(self) -> tuple[str, ...]:
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
            "requirements": self.requirements.to_dict(),
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
    "PresenterGrammar",
    "PresenterNode",
    "PresenterNodeType",
    "PresenterRequirements",
]
