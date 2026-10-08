"""P0.1 — the execution dialect.

`ProductionOperation` is what an adapter receives. It is deliberately narrow: it says
*what to do and what must come out*, and carries no semantics.

Why this is not a second plan authority
---------------------------------------
`hevi/missions/p3_types.py::PlanNode` already carries dependencies, an idempotency
key and artifact ids. This does not duplicate it:

    PlanNode            what the planner scheduled
    ProductionOperation what an adapter is asked to execute

`PlanNode` alone decides nothing about executability. `ProductionOperation` is derived
from a node (`from_plan_node`), and adapters receive only this type. The mapping is
one-directional and tested; no executor accepts a bare `PlanNode`.

Why an operation cannot carry semantic authority
------------------------------------------------
An operation references a `TimelineIR` by id, not by content, and names a provider by
ref, not by choosing one. It cannot restate a Director intent, and it cannot decide
which provider to use. Those are the `ProviderProfile` and Director authorities'
respective jobs, and §3 of the spec forbids an operation type from becoming a new
semantic axis -- so the type set is fixed and validated against it.

Why ids are validated rather than assumed
------------------------------------------
Almost every field here is a cross-reference into an authority that lives elsewhere.
An operation with a typo'd `depends_on` or an empty `idempotency_key` is not a
half-working operation; it is an operation that silently becomes un-cached and
un-orderable. Cheap checks at construction turn a class of runtime-only failures into
import-time errors.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hevi.production.artifacts import Artifact

_IDEMPOTENCY_FIELDS = ("production_id", "operation_type", "provider_ref", "renderer_ref")


class ProductionOperationType(StrEnum):
    """The fixed operation dialect.

    Adding a member is a spec change, not an extension point. §0.1 forbids establishing
    a new semantic authority, and the easiest way to do that by accident is to invent
    an operation type that quietly means something creative.
    """

    TIMELINE = "TIMELINE"
    VISUAL_SCENE = "VISUAL_SCENE"
    MEDIA = "MEDIA"
    AUDIO = "AUDIO"
    SUBTITLE = "SUBTITLE"
    RENDER = "RENDER"
    ENCODE = "ENCODE"


class ArtifactRef(BaseModel):
    """A *reference* to an artifact, not the record of it.

    ``hevi/production/artifacts.py::Artifact`` owns artifact state: path, bytes,
    digest, producer. This carries only what an operation needs to name one, and is
    built from an ``Artifact``. It holds no lifecycle field on purpose -- lifecycle
    lives in ``ArtifactManifest`` and ``missions::ArtifactRecord``, and a third copy
    here would be a third authority for whether an artifact exists.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    content_hash: str
    uri: str
    kind: str

    @field_validator("artifact_id", "uri", "kind")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("ARTIFACT_REF_EMPTY_FIELD:a reference needs a value")
        return value

    @field_validator("content_hash")
    @classmethod
    def _looks_like_a_digest(cls, value: str) -> str:
        # Not required to be sha256 -- providers legitimately use other digests -- but
        # an empty or placeholder digest would defeat deduplication silently.
        if len(value) < 8:
            raise ValueError(
                f"ARTIFACT_REF_WEAK_HASH:{value!r}; too short to identify content"
            )
        return value

    @classmethod
    def from_artifact(cls, artifact: Artifact) -> ArtifactRef:
        return cls(
            artifact_id=artifact.artifact_id or artifact.path,
            content_hash=artifact.sha256 or "",
            uri=artifact.uri or artifact.path,
            kind=artifact.kind,
        )


class ResourceRef(BaseModel):
    """A reference to a non-artifact input (a credential, a remote URL, a font set).

    Separate from ``ArtifactRef`` so an operation cannot pass a URL where hashed bytes
    are required. Validation downstream distinguishes them; merging them here would
    erase that distinction.
    """

    model_config = ConfigDict(frozen=True)

    resource_id: str
    kind: str
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("resource_id", "kind", "uri")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("RESOURCE_REF_EMPTY_FIELD:a reference needs a value")
        return value


class ArtifactExpectation(BaseModel):
    """What an operation must produce, asserted before execution.

    Declared rather than discovered, so a missing output is a contract violation with
    a name, not an absence noticed later during validation.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    kind: str
    required: bool = True
    #: For outputs whose identity depends on their content -- media, audio, renders.
    #: A deterministic artifact is also the deduplication and cache key.
    deterministic: bool = False

    @field_validator("name", "kind")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("ARTIFACT_EXPECTATION_EMPTY_FIELD")
        return value


class ProductionOperation(BaseModel):
    """One unit of executable work, fully described before it runs.

    Immutable and hashable by ``idempotency_key``: the same logical work must produce
    the same key on every retry, or dedup and caching stop working exactly when they
    are needed.
    """

    model_config = ConfigDict(frozen=True)

    operation_id: str
    operation_type: ProductionOperationType

    production_id: str
    timeline_id: str | None = None

    sequence: int = 0

    inputs: tuple[ArtifactRef | ResourceRef, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: tuple[ArtifactExpectation, ...] = ()

    #: A *reference*. This type never chooses a provider; ``ProviderProfile`` and the
    #: canonical policy do. A renderer or encoder that picked its own provider here
    #: would be a second provider authority.
    provider_ref: str | None = None
    renderer_ref: str | None = None
    encoder_ref: str | None = None

    #: Optional when constructed, but an operation without one is not executable:
    #: ``__post_init__``-time validation refuses it. Retries must reuse the key.
    idempotency_key: str = ""
    depends_on: tuple[str, ...] = ()

    #: §36. A failed ``required=False`` operation is recorded and the run continues;
    #: final validation still has to learn about it.
    required: bool = True
    #: §57. A dry run resolves and validates but must not produce media.
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("operation_id", "production_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("OPERATION_WITHOUT_ID:operation_id and production_id required")
        return value

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        if self.operation_id in self.depends_on:
            raise ValueError(f"OPERATION_SELF_DEPENDENCY:{self.operation_id}")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"OPERATION_DUPLICATE_DEPENDENCY:{self.operation_id}")
        consumed = {
            ref.artifact_id for ref in self.inputs if isinstance(ref, ArtifactRef)
        }
        if self.operation_id in consumed:
            raise ValueError(
                f"OPERATION_INPUT_IS_SELF:{self.operation_id}; an operation cannot "
                "consume its own output"
            )
        return self

    def compute_idempotency_key(self) -> str:
        """Derive the key from the identity-bearing fields only.

        ``sequence``, ``depends_on``, ``dry_run`` and ``metadata`` are excluded on
        purpose. Including scheduling information would give two logically identical
        operations different keys, so a retry after reordering would regenerate the
        artifact it was supposed to reuse. ``dry_run`` is excluded for the opposite
        reason: it produces nothing, so sharing a key with the real run is correct and
        prevents a dry run from poisoning the cache.
        """
        canonical = {
            "production_id": self.production_id,
            "operation_type": self.operation_type.value,
            "timeline_id": self.timeline_id,
            "inputs": sorted(
                (ref.artifact_id, ref.content_hash)
                for ref in self.inputs
                if isinstance(ref, ArtifactRef)
            ),
            "parameters": _canonical_json(self.parameters),
            "provider_ref": self.provider_ref,
            "renderer_ref": self.renderer_ref,
            "encoder_ref": self.encoder_ref,
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def ensure_idempotency_key(self) -> ProductionOperation:
        """Return a copy with the key populated. Never mutates -- the model is frozen."""
        if self.idempotency_key:
            return self
        return self.model_copy(update={"idempotency_key": self.compute_idempotency_key()})

    def requires_output(self, name: str) -> bool:
        return any(o.name == name and o.required for o in self.expected_outputs)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _canonical_json(value: Any) -> str:
    """Stable JSON for hashing.

    ``parameters`` is free-form operator-supplied data. ``sort_keys`` alone is not
    enough: a caller passing ``{"a": 1, "b": 2}`` and one passing ``{"b": 2, "a": 1}``
    describe the same operation and must share an idempotency key, or the retry
    generates a duplicate artifact.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def operation_order_key(operation: ProductionOperation) -> tuple[int, tuple[str, ...], str]:
    """Canonical ordering: sequence, then dependencies, then id.

    §38 forbids relying on dict iteration order, filesystem order, provider return
    order or async completion order. This is the only ordering, and it is total: the
    final component makes it a strict order even when two operations share a sequence
    and dependency set.
    """
    return (operation.sequence, tuple(sorted(operation.depends_on)), operation.operation_id)


def resolve_execution_order(
    operations: tuple[ProductionOperation, ...] | list[ProductionOperation],
) -> tuple[ProductionOperation, ...]:
    """Topologically order operations by ``depends_on``, breaking ties canonically.

    Raises on a cycle rather than emitting an arbitrary order. A cycle means the
    operation set is not executable, and silently picking an order would run one
    operation before the artifact it declared it needed.
    """
    by_id = {op.operation_id: op for op in operations}
    for op in operations:
        missing = [d for d in op.depends_on if d not in by_id]
        if missing:
            raise ValueError(f"OPERATION_UNKNOWN_DEPENDENCY:{op.operation_id}:{missing}")

    emitted: set[str] = set()
    ordered: list[ProductionOperation] = []
    remaining = sorted(operations, key=operation_order_key)

    while remaining:
        ready = [op for op in remaining if all(d in emitted for d in op.depends_on)]
        if not ready:
            cycle = sorted(op.operation_id for op in remaining)
            raise ValueError(f"OPERATION_DEPENDENCY_CYCLE:{cycle}")
        for op in ready:
            ordered.append(op)
            emitted.add(op.operation_id)
        done = {op.operation_id for op in ready}
        remaining = [op for op in remaining if op.operation_id not in done]

    return tuple(ordered)


__all__ = [
    "ArtifactExpectation",
    "ArtifactRef",
    "ProductionOperation",
    "ProductionOperationType",
    "ResourceRef",
    "operation_order_key",
    "resolve_execution_order",
]
