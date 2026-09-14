"""Small deterministic state operations for the creative runtime.

The primitive accepts a typed proposal and returns a newly validated model.
It never mutates the supplied canonical object in place and rejects stale or
authority-changing proposals.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hevi.obase.creative import CreativeAuthority, CreativeObject

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | tuple[JsonScalar, ...]

class StateOperation(BaseModel):
    """A deliberately narrow top-level update operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: JsonValue


class CreativeStateDelta(BaseModel):
    """LLM/module proposal; it is not canonical state authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str
    project_id: str
    target_type: str
    base_revision: int = Field(ge=0)
    operations: tuple[StateOperation, ...] = ()
    authority: CreativeAuthority = CreativeAuthority.PROPOSAL

    @model_validator(mode="after")
    def proposal_only(self) -> CreativeStateDelta:
        if self.authority is not CreativeAuthority.PROPOSAL:
            raise ValueError("state deltas must remain proposals until explicitly committed")
        return self


_PROTECTED_PATHS = {
    "authority",
    "content_hash",
    "created_at",
    "object_id",
    "project_id",
    "provenance",
    "revision",
    "schema_version",
    "updated_at",
}


def canonical_json(value: Any) -> str:
    """Serialize JSON-compatible values deterministically."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compare_versions(current: CreativeObject, expected_revision: int) -> None:
    if current.revision != expected_revision:
        raise ValueError(
            f"STALE_REVISION: expected {expected_revision}, current {current.revision}"
        )


def apply_state_delta[T: CreativeObject](
    current: T,
    delta: CreativeStateDelta,
) -> T:
    """Validate and return a committed copy of a proposal.

    This is a commit primitive, not an LLM write path.  Callers must still
    persist the returned object atomically with their artifact transaction.
    """

    if str(current.object_id) != delta.target_id:
        raise ValueError("state delta target does not match canonical object")
    if str(current.project_id) != delta.project_id:
        raise ValueError("state delta project does not match canonical object")
    compare_versions(current, delta.base_revision)

    updates: dict[str, Any] = {}
    fields = type(current).model_fields
    for operation in delta.operations:
        if operation.path in _PROTECTED_PATHS:
            raise ValueError(f"PROTECTED_STATE_PATH: {operation.path}")
        if operation.path not in fields:
            raise ValueError(f"UNKNOWN_STATE_PATH: {operation.path}")
        updates[operation.path] = operation.value

    updates["revision"] = current.revision + 1
    updates["updated_at"] = datetime.now(UTC)
    updates["authority"] = CreativeAuthority.CANONICAL
    return type(current).model_validate(current.model_dump() | updates)


__all__ = [
    "CreativeStateDelta",
    "StateOperation",
    "apply_state_delta",
    "canonical_json",
    "compare_versions",
    "hash_bytes",
]
