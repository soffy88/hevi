"""P10a error model: typed codes, no silent fallback."""

from __future__ import annotations


class DirectionStateError(Exception):
    code: str = "DIRECTION_STATE_ERROR"

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        if code:
            self.code = code


class IllegalTransitionError(DirectionStateError):
    code = "ILLEGAL_TRANSITION"


class ConflictError(DirectionStateError):
    code = "CONFLICT_STALE_STATE"


class DuplicateCommandError(DirectionStateError):
    """Raised only when a duplicate command disagrees with history; same-command
    replay returns the recorded outcome without mutation (idempotent)."""

    code = "DUPLICATE_COMMAND"


class MissingBindingError(DirectionStateError):
    code = "MISSING_BINDING"


class RevisionImmutableError(DirectionStateError):
    code = "REVISION_IMMUTABLE"


class PersistenceError(DirectionStateError):
    code = "PERSISTENCE_FAILED"


class RevisionNotFoundError(DirectionStateError):
    code = "REVISION_NOT_FOUND"
