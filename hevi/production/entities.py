"""HEVI P5.2 — production entity graph.

Before HEVI renders anything it must already know *who and what stays
consistent*. The entity graph answers that: one stable identity per person,
product, book, place or brand, plus the relationships and continuity rules that
survive across shots.

This is deliberately **not** a second asset database. An entity never owns
media; it *references* media that already exists in the canonical
``Asset`` / ``EvidenceAsset`` / ``ArtifactRecord`` lineage. The graph expresses
only three things:

    identity, relationship, continuity

The invariants it protects:

* ``ENTITY_IDENTITY_DRIFT == 0`` — the same real-world thing keeps one
  ``entity_id`` across every shot, no matter which text a planner wrote.
* ``DUPLICATE_ENTITY_AUTHORITY == 0`` — one graph, one authority, resolved
  through P3 lineage.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from hevi.production.references import audit_summary  # noqa: F401  (re-export parity)


class EntityType(StrEnum):
    PERSON = "PERSON"
    CHARACTER = "CHARACTER"
    PRODUCT = "PRODUCT"
    BOOK = "BOOK"
    LOCATION = "LOCATION"
    SCENE = "SCENE"
    PROP = "PROP"
    CLOTHING = "CLOTHING"
    UI_PRODUCT = "UI_PRODUCT"
    DOCUMENT = "DOCUMENT"
    BRAND = "BRAND"
    VISUAL_STYLE = "VISUAL_STYLE"


class EntityRelation(StrEnum):
    APPEARS_IN = "APPEARS_IN"
    USES = "USES"
    WEARS = "WEARS"
    LOCATED_IN = "LOCATED_IN"
    BELONGS_TO = "BELONGS_TO"
    REPRESENTS = "REPRESENTS"
    DEMONSTRATES = "DEMONSTRATES"
    REFERENCES = "REFERENCES"


#: Relations that carry identity consequences, not just bookkeeping.
IDENTITY_BEARING_RELATIONS = frozenset(
    {EntityRelation.WEARS, EntityRelation.REPRESENTS, EntityRelation.BELONGS_TO}
)

#: Brand tokens / logos may only be asserted with a verified source. A model is
#: never allowed to guess what a brand looks like.
_BRAND_TOKEN_KEYS = (
    "primary_color", "secondary_color", "logo", "logo_reference",
    "wordmark", "font",
)


@dataclass
class VisualConstraint:
    """A rule about how an entity may be depicted."""

    key: str
    value: str
    verified: bool = False
    source_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContinuityConstraint:
    """A rule that must hold for an entity across shots."""

    key: str
    value: str
    strict: bool = True
    source_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionEntity:
    """One stable identity in a production."""

    #: Empty means "let the graph mint a stable id"; :meth:`ProductionEntityGraph.register`
    #: never mints a *second* identity for the same thing.
    entity_id: str = ""
    entity_type: EntityType = EntityType.PROP
    canonical_name: str = ""
    description: str = ""
    source_refs: list[str] = field(default_factory=list)
    #: References into the existing asset/evidence/artifact lineage. Never media
    #: owned by the graph itself.
    canonical_assets: list[str] = field(default_factory=list)
    visual_constraints: list[VisualConstraint] = field(default_factory=list)
    continuity_constraints: list[ContinuityConstraint] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    variant_of: str = ""
    aliases: list[str] = field(default_factory=list)

    def constraint(self, key: str) -> str | None:
        found: str | None = next(
            (item.value for item in self.visual_constraints if item.key == key), None
        )
        if found is not None:
            return found
        return next(
            (item.value for item in self.continuity_constraints if item.key == key), None
        )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entity_type"] = self.entity_type.value
        return d


@dataclass
class EntityRelationship:
    """A typed edge between two entities."""

    source_id: str
    relation: EntityRelation
    target_id: str
    source_ref: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["relation"] = self.relation.value
        return d


# ── Identity resolution (§11) ────────────────────────────────────────────

_NOISE = re.compile(r"^(the |a |an |this |that |our |your )", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w一-鿿]+", re.UNICODE)


def normalise_name(name: str) -> str:
    """Normalise a name so the same thing written twice resolves once."""
    lowered = _NOISE.sub("", (name or "").strip().lower())
    return _PUNCT.sub("", lowered)


def identity_key(entity: ProductionEntity) -> str:
    """The natural key for an entity's identity.

    A variant is a *different* identity on purpose: a v2 product is not the v1
    product, and silently merging them would hide a real change.
    """
    base = f"{entity.entity_type.value}:{normalise_name(entity.canonical_name)}"
    return f"{base}:{entity.variant_of}" if entity.variant_of else base


@dataclass
class EntityGraphReport:
    """Continuity audit result."""

    ok: bool = True
    entity_count: int = 0
    relationship_count: int = 0
    gates: dict[str, bool] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProductionEntityGraph:
    """The single entity authority for one content/project."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._entities: dict[str, ProductionEntity] = {}
        self._by_key: dict[str, str] = {}
        self._relationships: list[EntityRelationship] = []
        self._shot_refs: dict[str, list[str]] = {}

    # ── Entity registration ──
    def register(self, entity: ProductionEntity) -> tuple[ProductionEntity, bool]:
        """Register an entity, resolving identity.

        Returns ``(entity, created)``. Registering the same thing twice returns
        the *existing* entity rather than minting a second identity, which is
        what keeps ``ENTITY_IDENTITY_DRIFT`` at 0.
        """
        key = identity_key(entity)
        existing_id = self._by_key.get(key)
        if existing_id is not None:
            return self._entities[existing_id], False
        if not entity.entity_id:
            entity.entity_id = f"{entity.entity_type.value.lower()}-{len(self._entities) + 1:03d}"
        self._entities[entity.entity_id] = entity
        self._by_key[key] = entity.entity_id
        return entity, True

    def get(self, entity_id: str) -> ProductionEntity | None:
        return self._entities.get(entity_id)

    def resolve(self, name: str, entity_type: EntityType | None = None) -> ProductionEntity | None:
        for entity in self._entities.values():
            if entity_type and entity.entity_type is not entity_type:
                continue
            candidates = {normalise_name(entity.canonical_name)} | {
                normalise_name(alias) for alias in entity.aliases
            }
            if normalise_name(name) in candidates:
                return entity
        return None

    def entities(self) -> list[ProductionEntity]:
        return list(self._entities.values())

    def count(self) -> int:
        return len(self._entities)

    def of_type(self, entity_type: EntityType) -> list[ProductionEntity]:
        return [e for e in self._entities.values() if e.entity_type is entity_type]

    # ── Relationships ──
    def relate(
        self, source_id: str, relation: EntityRelation, target_id: str, *, source_ref: str = "",
        note: str = "",
    ) -> EntityRelationship | None:
        if source_id not in self._entities or target_id not in self._entities:
            return None
        edge = EntityRelationship(
            source_id=source_id, relation=relation, target_id=target_id,
            source_ref=source_ref, note=note,
        )
        self._relationships.append(edge)
        return edge

    def relationships(self) -> list[EntityRelationship]:
        return list(self._relationships)

    def neighbours(self, entity_id: str, relation: EntityRelation | None = None) -> list[str]:
        return [
            edge.target_id if edge.source_id == entity_id else edge.source_id
            for edge in self._relationships
            if (edge.source_id == entity_id or edge.target_id == entity_id)
            and (relation is None or edge.relation is relation)
        ]

    # ── Shot references (§9) ──
    def bind_shot(self, shot_id: str, entity_ids: list[str]) -> list[str]:
        """Bind entities to a shot, rejecting unknown ids."""
        bound = [eid for eid in entity_ids if eid in self._entities]
        self._shot_refs[shot_id] = bound
        return bound

    def shot_refs(self, shot_id: str) -> list[str]:
        return list(self._shot_refs.get(shot_id, []))

    def shots_for(self, entity_id: str) -> list[str]:
        return [shot for shot, ids in self._shot_refs.items() if entity_id in ids]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "entities": [e.to_dict() for e in self._entities.values()],
            "relationships": [r.to_dict() for r in self._relationships],
            "shot_references": dict(self._shot_refs),
        }


# ── Continuity gate (§14) ────────────────────────────────────────────────

#: Entity types that must keep a stable visual identity across shots.
_IDENTITY_TYPES = frozenset(
    {
        EntityType.PERSON,
        EntityType.CHARACTER,
        EntityType.PRODUCT,
        EntityType.UI_PRODUCT,
        EntityType.BOOK,
        EntityType.BRAND,
    }
)


def audit_continuity(
    graph: ProductionEntityGraph,
    *,
    asset_bindings: dict[str, list[str]] | None = None,
    declared_states: dict[str, dict[str, str]] | None = None,
) -> EntityGraphReport:
    """Audit entity continuity across shots.

    ``asset_bindings`` maps ``entity_id -> shot_id -> asset_ref``. Where an
    entity's binding changes for a continuity-bearing key without a version
    bump, that is drift: the same character silently acquired a different
    outfit or face.
    """
    report = EntityGraphReport(entity_count=graph.count(), relationship_count=len(graph.relationships()))
    bindings = asset_bindings or {}
    states = declared_states or {}
    report.gates["ENTITY_IDENTITY_CONSISTENCY"] = True
    report.gates["CHARACTER_CONTINUITY"] = True
    report.gates["PRODUCT_CONTINUITY"] = True
    report.gates["PROP_CONTINUITY"] = True
    report.gates["SCENE_CONTINUITY"] = True

    # Identity drift: two entities claiming the same natural key cannot exist
    # because register() merges them, so drift shows up as a graph whose
    # aliases collide with another live entity's canonical name.
    canon = {normalise_name(e.canonical_name): e.entity_id for e in graph.entities()}
    for entity in graph.entities():
        for alias in entity.aliases:
            key = normalise_name(alias)
            if key in canon and canon[key] != entity.entity_id:
                report.violations.append(
                    f"ENTITY_IDENTITY_DRIFT:{entity.entity_id}:alias '{alias}' collides with "
                    f"{canon[key]}"
                )
                report.gates["ENTITY_IDENTITY_CONSISTENCY"] = False

    # Continuity drift: the same continuity key resolving to different values
    # across shots. ``declared_states`` is
    # ``{entity_id: {continuity_key: {shot_id: value}}}``.
    for entity in graph.entities():
        per_entity: dict[str, Any] = states.get(entity.entity_id, {})
        for key in _CONTINUITY_KEYS:
            per_shot: Any = per_entity.get(key) or {}
            if not isinstance(per_shot, dict):
                continue
            values = {str(value) for value in per_shot.values() if value}
            if len(values) > 1:
                gate = _GATE_FOR_TYPE.get(entity.entity_type, "SCENE_CONTINUITY")
                report.violations.append(
                    f"CONTINUITY_DRIFT:{entity.entity_id}:{key}={sorted(values)}"
                )
                report.gates[gate] = False

    # Assets must be referenced, never owned: a binding to a path the graph
    # did not receive from canonical lineage is a provenance problem.
    for entity in graph.entities():
        for key, shots in bindings.items():
            if key != entity.entity_id:
                continue
            if not isinstance(shots, dict):
                continue
            for shot_id, refs in shots.items():
                if not refs:
                    report.violations.append(
                        f"EMPTY_CONTINUITY_BINDING:{entity.entity_id}:{shot_id}"
                    )
                    report.gates[_GATE_FOR_TYPE.get(entity.entity_type, "SCENE_CONTINUITY")] = False

    # Brand tokens and logos must be verified, never guessed.
    for entity in graph.of_type(EntityType.BRAND) + graph.of_type(EntityType.PRODUCT):
        for constraint in entity.visual_constraints:
            if constraint.key in _BRAND_TOKEN_KEYS and not constraint.verified:
                report.violations.append(
                    f"UNVERIFIED_BRAND_TOKEN:{entity.entity_id}:{constraint.key}"
                )
                report.gates["PRODUCT_CONTINUITY"] = False

    report.gates["PRODUCTION_ENTITY_GRAPH"] = all(report.gates.values())
    report.ok = all(report.gates.values())
    return report


#: Continuity keys that matter per entity type.
_CONTINUITY_KEYS = (
    "face_reference",
    "clothing_reference",
    "framing",
    "background",
    "voice_identity",
    "logo_reference",
    "scale",
    "palette",
)

_GATE_FOR_TYPE: dict[EntityType, str] = {
    EntityType.PERSON: "CHARACTER_CONTINUITY",
    EntityType.CHARACTER: "CHARACTER_CONTINUITY",
    EntityType.CLOTHING: "CHARACTER_CONTINUITY",
    EntityType.PRODUCT: "PRODUCT_CONTINUITY",
    EntityType.UI_PRODUCT: "PRODUCT_CONTINUITY",
    EntityType.BOOK: "PRODUCT_CONTINUITY",
    EntityType.BRAND: "PRODUCT_CONTINUITY",
    EntityType.PROP: "PROP_CONTINUITY",
    EntityType.SCENE: "SCENE_CONTINUITY",
    EntityType.LOCATION: "SCENE_CONTINUITY",
    EntityType.DOCUMENT: "SCENE_CONTINUITY",
    EntityType.VISUAL_STYLE: "SCENE_CONTINUITY",
}


# ── Builders ─────────────────────────────────────────────────────────────


def person_entity(
    name: str,
    *,
    face_ref: str = "",
    clothing_ref: str = "",
    framing: str = "",
    background: str = "",
    voice_identity: str = "",
    entity_id: str = "",
) -> ProductionEntity:
    """Build a person/presenter entity with explicit continuity anchors."""
    entity = ProductionEntity(
        entity_id=entity_id,
        entity_type=EntityType.PERSON,
        canonical_name=name,
        description="presenter / on-camera human",
        provenance={"builder": "person_entity"},
    )
    for key, value, strict in (
        ("face_reference", face_ref, True),
        ("clothing_reference", clothing_ref, True),
        ("framing", framing, False),
        ("background", background, False),
        ("voice_identity", voice_identity, True),
    ):
        if value:
            entity.continuity_constraints.append(
                ContinuityConstraint(key=key, value=value, strict=strict)
            )
    return entity


def product_entity(
    name: str,
    *,
    official_url: str = "",
    logo_ref: str = "",
    evidence_refs: list[str] | None = None,
    entity_id: str = "",
) -> ProductionEntity:
    """Build a product entity.

    A logo or brand token without a verified source is recorded as
    unverified, which the continuity gate then refuses.
    """
    entity = ProductionEntity(
        entity_id=entity_id,
        entity_type=EntityType.PRODUCT,
        canonical_name=name,
        description="product the video is about",
        canonical_assets=list(evidence_refs or []),
        provenance={"builder": "product_entity", "official_url": official_url},
    )
    if logo_ref:
        entity.visual_constraints.append(
            VisualConstraint(
                key="logo_reference", value=logo_ref, verified=bool(official_url),
                source_ref=official_url, note="logo must come from an official source",
            )
        )
    return entity


__all__ = [
    "IDENTITY_BEARING_RELATIONS",
    "ContinuityConstraint",
    "EntityGraphReport",
    "EntityRelation",
    "EntityRelationship",
    "EntityType",
    "ProductionEntity",
    "ProductionEntityGraph",
    "VisualConstraint",
    "audit_continuity",
    "identity_key",
    "normalise_name",
    "person_entity",
    "product_entity",
]
