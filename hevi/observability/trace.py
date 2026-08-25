"""Trace and production-context propagation helpers.

The context is deliberately kept in a ``ContextVar`` so concurrent FastAPI
requests and worker tasks cannot leak identifiers into one another.  The
actual trace id remains owned by ``obase`` for compatibility with the rest of
the platform; this module adds the production identifiers carried alongside
it.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields

from obase.tracing import current_trace_id as get_trace_id
from obase.tracing import start_trace as _obase_start_trace


@dataclass(frozen=True, slots=True)
class TraceContext:
    """Identifiers shared by logs, metrics, events, and provider calls."""

    trace_id: str | None = None
    production_id: str | None = None
    revision_id: str | None = None
    plan_id: str | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    node_id: str | None = None
    provider_call_id: str | None = None
    artifact_id: str | None = None
    evaluation_id: str | None = None

    def log_fields(self) -> dict[str, str]:
        """Return only populated identifiers for structured logs."""
        return {
            field.name: value
            for field in fields(self)
            if (value := getattr(self, field.name)) is not None
        }


_current_context: ContextVar[TraceContext | None] = ContextVar("hevi_trace_context", default=None)


def current_trace_context() -> TraceContext:
    """Return the current immutable context snapshot."""
    context = _current_context.get() or TraceContext()
    # A caller may enter an obase trace directly. Keep the exported context
    # useful even in that case without mutating the ContextVar.
    trace_id = get_trace_id()
    if context.trace_id == trace_id:
        return context
    return TraceContext(
        trace_id=trace_id,
        production_id=context.production_id,
        revision_id=context.revision_id,
        plan_id=context.plan_id,
        task_id=context.task_id,
        attempt_id=context.attempt_id,
        node_id=context.node_id,
        provider_call_id=context.provider_call_id,
        artifact_id=context.artifact_id,
        evaluation_id=context.evaluation_id,
    )


@contextmanager
def start_trace(trace_id: str | None = None) -> Generator[str]:
    """Start an obase trace and bind its id to the Hevi context."""
    with _obase_start_trace(trace_id) as tid:
        token = _current_context.set(TraceContext(trace_id=tid))
        try:
            yield tid
        finally:
            _current_context.reset(token)


@contextmanager
def bind_trace_context(**identifiers: str | None) -> Generator[TraceContext]:
    """Temporarily bind one or more RFC trace identifiers.

    Unknown keys are ignored to prevent accidental high-cardinality data from
    becoming part of the shared context. Values are stringified at the edge so
    UUIDs and database-native identifiers are safe to pass directly.
    """
    current = current_trace_context()
    allowed = {field.name for field in fields(TraceContext)} - {"trace_id"}
    updates = {
        key: (None if value is None else str(value))
        for key, value in identifiers.items()
        if key in allowed
    }
    bound = TraceContext(
        trace_id=current.trace_id,
        production_id=updates.get("production_id", current.production_id),
        revision_id=updates.get("revision_id", current.revision_id),
        plan_id=updates.get("plan_id", current.plan_id),
        task_id=updates.get("task_id", current.task_id),
        attempt_id=updates.get("attempt_id", current.attempt_id),
        node_id=updates.get("node_id", current.node_id),
        provider_call_id=updates.get("provider_call_id", current.provider_call_id),
        artifact_id=updates.get("artifact_id", current.artifact_id),
        evaluation_id=updates.get("evaluation_id", current.evaluation_id),
    )
    token = _current_context.set(bound)
    try:
        yield bound
    finally:
        _current_context.reset(token)


__all__ = [
    "TraceContext",
    "bind_trace_context",
    "current_trace_context",
    "get_trace_id",
    "start_trace",
]
