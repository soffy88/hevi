import contextvars
from uuid import UUID

# Context variable to hold the current trace_id (task_id)
_trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)


def set_trace_id(trace_id: str | UUID) -> None:
    """Set the current trace_id in the context."""
    _trace_id_ctx.set(str(trace_id))


def get_trace_id() -> str | None:
    """Retrieve the current trace_id from the context."""
    return _trace_id_ctx.get()
