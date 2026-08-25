"""Canonical task lifecycle rules.

The API projection and the worker both write ``video_tasks.status``.  Keeping
the transition table in one small module lets the repository enforce the same
truth regardless of which caller owns the current attempt.
"""

from __future__ import annotations


class InvalidTaskTransition(ValueError):
    """Raised when a task status would skip an allowed lifecycle boundary."""


# ``completed`` and ``cancelled`` are terminal for the current task revision.
# A failed/interrupted/paused task may be explicitly requeued or resumed; this
# is how recovery remains durable without silently creating a second owner.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"pending", "queued", "running", "failed", "cancelled", "paused"}),
    "queued": frozenset({"queued", "claimed", "running", "failed", "cancelled", "paused"}),
    "claimed": frozenset({"claimed", "running", "queued", "failed", "cancelled", "paused", "interrupted"}),
    "running": frozenset({"running", "completed", "failed", "cancelled", "paused", "interrupted", "queued"}),
    "paused": frozenset({"paused", "queued", "running", "failed", "cancelled"}),
    "failed": frozenset({"failed", "queued", "running", "cancelled"}),
    "interrupted": frozenset({"interrupted", "queued", "running", "failed", "cancelled"}),
    "completed": frozenset({"completed"}),
    "cancelled": frozenset({"cancelled"}),
}


def validate_task_transition(previous: str, current: str) -> None:
    """Validate a task lifecycle transition.

    Same-state writes are always valid because progress, checkpoints and
    provider decisions update other fields while the task remains in place.
    """

    if previous == current:
        return
    allowed = TASK_TRANSITIONS.get(previous)
    if allowed is None or current not in allowed:
        raise InvalidTaskTransition(f"invalid task transition: {previous!r} -> {current!r}")


__all__ = ["TASK_TRANSITIONS", "InvalidTaskTransition", "validate_task_transition"]
