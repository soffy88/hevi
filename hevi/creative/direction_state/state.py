"""P10a minimal data contracts (§6). Frozen dataclasses; no content fields."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Lifecycle(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED = "APPROVED"
    COMPILED = "COMPILED"
    IN_PRODUCTION = "IN_PRODUCTION"
    VERIFIED = "VERIFIED"
    REVISION_PROPOSED = "REVISION_PROPOSED"


@dataclass(frozen=True)
class DirectionState:
    project_id: str
    direction_id: str
    revision: int
    lifecycle: Lifecycle
    updated_at: str = ""
    version: int = 1  # state record version, bumped per transition
    compile_receipt: str = ""
    artifact_hash: str = ""
    # Director Contract V1 binding; defaults preserve legacy snapshots.
    proposal_hash: str = ""
    approved_proposal_hash: str = ""


@dataclass(frozen=True)
class TransitionCommand:
    command_id: str
    project_id: str
    direction_id: str
    revision: int
    action: str
    expected_state: str = ""
    actor: str = ""
    reason: str = ""
    idempotency_key: str = ""


@dataclass(frozen=True)
class TransitionEvent:
    event_id: str
    command_id: str
    project_id: str
    direction_id: str
    revision: int
    from_state: str
    action: str
    to_state: str
    actor: str = ""
    reason: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class ReviewEvent:
    action: str  # REJECT only; REQUEST_CHANGES is a lifecycle transition
    revision: int
    reason: str
    actor: str = ""
    command_id: str = ""
