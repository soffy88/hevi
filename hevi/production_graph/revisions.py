"""Validated Director decisions and immutable canonical revisions.

Agents receive a narrow patch interface. They do not receive a repository or
an ORM session, so a decision cannot silently mutate production state. The
patch is validated against a snapshot, locks, and referential integrity before
the repository is asked to persist the child revision.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from hevi.production_graph.domain import (
    Beat,
    CanonicalShot,
    Character,
    CharacterState,
    DirectorDecision,
    DirectorSession,
    DirectorSessionStatus,
    Episode,
    Keyframe,
    Location,
    LocationState,
    LookVariant,
    ProductionGraphSnapshot,
    ProductionPlan,
    ProductionProject,
    ProductionRevision,
    Prop,
    PropState,
    ReferenceBundle,
    RevisionPatch,
    RevisionPatchOperation,
    Scene,
    Season,
    SourceChunk,
    SourceDocument,
    World,
    WorldRule,
)
from hevi.production_graph.ids import new_id


class RevisionPatchError(ValueError):
    """Raised when a creative patch is invalid or attempts to bypass a lock."""


_COLLECTIONS: dict[str, tuple[str, type[BaseModel]]] = {
    "sources": ("sources", SourceDocument),
    "source_chunks": ("source_chunks", SourceChunk),
    "characters": ("characters", Character),
    "character_states": ("character_states", CharacterState),
    "look_variants": ("look_variants", LookVariant),
    "worlds": ("worlds", World),
    "world_rules": ("world_rules", WorldRule),
    "locations": ("locations", Location),
    "location_states": ("location_states", LocationState),
    "props": ("props", Prop),
    "prop_states": ("prop_states", PropState),
    "seasons": ("seasons", Season),
    "episodes": ("episodes", Episode),
    "scenes": ("scenes", Scene),
    "beats": ("beats", Beat),
    "shots": ("shots", CanonicalShot),
    "keyframes": ("keyframes", Keyframe),
    "reference_bundles": ("reference_bundles", ReferenceBundle),
    "production_plans": ("production_plans", ProductionPlan),
}


def create_director_session(
    project: ProductionProject,
    *,
    objective: str,
    constraints: Iterable[str] = (),
    memory_scope: str = "PROJECT",
) -> DirectorSession:
    """Create a persistent session record without changing the project."""

    revision_id = project.current_revision_id
    if not revision_id:
        raise RevisionPatchError("director session requires a current project revision")
    if not objective.strip():
        raise RevisionPatchError("director session objective cannot be empty")
    return DirectorSession(
        project_id=project.id,
        current_revision_id=revision_id,
        objective=objective,
        constraints=list(constraints),
        memory_scope=memory_scope,
    )


def record_director_decision(
    session: DirectorSession,
    *,
    decision_type: str,
    inputs: dict[str, Any] | None = None,
    rationale: str = "",
    patch: RevisionPatch | None = None,
) -> DirectorDecision:
    """Return an inspectable decision; applying it remains a separate step."""

    if session.status is not DirectorSessionStatus.OPEN:
        raise RevisionPatchError(f"director session is {session.status}, not OPEN")
    if patch is not None and patch.project_id != session.project_id:
        raise RevisionPatchError("decision patch belongs to another project")
    return DirectorDecision(
        session_id=session.id,
        project_id=session.project_id,
        decision_type=decision_type,
        inputs=dict(inputs or {}),
        rationale=rationale,
        output_patch_id=patch.id if patch else None,
        revision_id=session.current_revision_id,
    )


def validate_revision_patch(snapshot: ProductionGraphSnapshot, patch: RevisionPatch) -> None:
    if patch.project_id != snapshot.project.id:
        raise RevisionPatchError("revision patch belongs to another project")
    if patch.base_revision_id != snapshot.revision.id:
        raise RevisionPatchError("revision patch is based on a stale revision")
    if not patch.actor.strip():
        raise RevisionPatchError("revision patch actor is required")
    if not patch.operations:
        raise RevisionPatchError("revision patch must contain at least one operation")
    for operation in patch.operations:
        _validate_operation(snapshot, operation)


def _validate_operation(snapshot: ProductionGraphSnapshot, operation: RevisionPatchOperation) -> None:
    parts = _path_parts(operation.path)
    collection_name = parts[0]
    if collection_name not in _COLLECTIONS:
        raise RevisionPatchError(f"unsupported canonical patch collection: {collection_name}")
    records = getattr(snapshot, _COLLECTIONS[collection_name][0])
    if operation.op == "add":
        if len(parts) == 1 or parts[1] == "-":
            return
        raise RevisionPatchError("add only supports appending a canonical entity")
    if len(parts) < 3:
        raise RevisionPatchError("replace/remove requires /collection/entity_id/field")
    record = next((item for item in records if item.id == parts[1]), None)
    if record is None:
        raise RevisionPatchError(f"unknown {collection_name} entity: {parts[1]}")
    _assert_unlocked(record, collection_name)
    if operation.op == "remove":
        raise RevisionPatchError("removing canonical entities is not allowed in P0; archive them")
    _assert_field_exists(record, parts[2:])


def _path_parts(path: str) -> list[str]:
    if not path.startswith("/"):
        raise RevisionPatchError("patch path must be an absolute JSON pointer")
    parts = [part for part in path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise RevisionPatchError("patch path cannot contain traversal segments")
    if len(parts) < 1:
        raise RevisionPatchError("patch path cannot be empty")
    return parts


def _assert_field_exists(record: BaseModel, parts: list[str]) -> None:
    current: Any = record
    for index, part in enumerate(parts):
        if isinstance(current, BaseModel):
            if part not in current.model_fields:
                raise RevisionPatchError(f"unknown canonical field: {'/'.join(parts)}")
            current = getattr(current, part)
        elif isinstance(current, dict):
            if part not in current:
                raise RevisionPatchError(f"unknown canonical map field: {'/'.join(parts)}")
            current = current[part]
        elif index < len(parts) - 1:
            raise RevisionPatchError(f"field is not traversable: {'/'.join(parts)}")


def _assert_unlocked(record: BaseModel, collection_name: str) -> None:
    if isinstance(record, CanonicalShot) and str(record.readiness_state) == "LOCKED":
        raise RevisionPatchError(f"locked shot cannot be modified: {record.id}")
    if isinstance(record, (Keyframe, ReferenceBundle)) and record.locked:
        raise RevisionPatchError(f"locked {collection_name[:-1]} cannot be modified: {record.id}")
    if isinstance(record, LookVariant) and record.lifecycle == "LOCKED":
        raise RevisionPatchError(f"locked look variant cannot be modified: {record.id}")


def apply_revision_patch(
    snapshot: ProductionGraphSnapshot,
    patch: RevisionPatch,
) -> ProductionGraphSnapshot:
    """Validate a patch and return a fully isolated child snapshot."""

    validate_revision_patch(snapshot, patch)
    revision = ProductionRevision(
        project_id=snapshot.project.id,
        parent_revision_id=snapshot.revision.id,
        revision_no=snapshot.revision.revision_no + 1,
        actor=patch.actor,
        reason=patch.reason,
    )
    project = snapshot.project.model_copy(
        update={"current_revision_id": revision.id, "updated_at": datetime.now(UTC)}
    )
    child = snapshot.model_copy(update={"project": project, "revision": revision}, deep=True)
    for operation in patch.operations:
        _apply_operation(child, operation)
    child.revision_patches.append(patch.model_copy(update={"revision_id": revision.id}))
    _rebind_revision_ids(child, revision.id)
    child.validate_referential_integrity()
    return child


def _apply_operation(snapshot: ProductionGraphSnapshot, operation: RevisionPatchOperation) -> None:
    parts = _path_parts(operation.path)
    collection_name, collection_type = _COLLECTIONS[parts[0]]
    records = getattr(snapshot, collection_name)
    if operation.op == "add":
        value = operation.value
        if not isinstance(value, collection_type):
            value = collection_type.model_validate(value)
        records.append(value)
        return
    index = next(index for index, item in enumerate(records) if item.id == parts[1])
    record = records[index]
    records[index] = _update_nested(record, parts[2:], operation.value)


def _update_nested(record: BaseModel, parts: list[str], value: Any) -> BaseModel:
    if len(parts) == 1:
        return record.model_copy(update={parts[0]: value})
    field = parts[0]
    current = getattr(record, field)
    if isinstance(current, BaseModel):
        current = _update_nested(current, parts[1:], value)
    elif isinstance(current, dict):
        if len(parts) != 2:
            raise RevisionPatchError("nested map patches are limited to one field in P0")
        updated = dict(current)
        updated[parts[1]] = value
        current = updated
    else:
        raise RevisionPatchError(f"field is not traversable: {'/'.join(parts)}")
    return record.model_copy(update={field: current})


def _rebind_revision_ids(snapshot: ProductionGraphSnapshot, revision_id: str) -> None:
    """Every versioned entity in a child snapshot points at the child revision."""

    for field_name in type(snapshot).model_fields:
        value = getattr(snapshot, field_name)
        if isinstance(value, list):
            setattr(
                snapshot,
                field_name,
                [
                    item.model_copy(update={"revision_id": revision_id})
                    if isinstance(item, BaseModel) and "revision_id" in type(item).model_fields
                    else item
                    for item in value
                ],
            )
    if snapshot.narrative is not None:
        snapshot.narrative = snapshot.narrative.model_copy(update={"revision_id": revision_id})


__all__ = [
    "RevisionPatchError",
    "apply_revision_patch",
    "create_director_session",
    "record_director_decision",
    "validate_revision_patch",
]
