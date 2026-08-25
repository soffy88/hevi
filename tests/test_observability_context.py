"""Tests for RFC 12 trace context and operational probes."""

import json

from hevi.observability import (
    bind_trace_context,
    current_trace_context,
    log_event,
    start_trace,
)


def test_trace_context_is_nested_and_does_not_leak(caplog) -> None:
    caplog.set_level("INFO", logger="hevi.structured")
    with start_trace("trace-1"):
        with bind_trace_context(
            production_id="production-1", revision_id="revision-1", task_id="task-1"
        ):
            log_event(stage="worker", event="claimed")
            data = json.loads(caplog.records[-1].message)
            assert data["trace_id"] == "trace-1"
            assert data["production_id"] == "production-1"
            assert data["revision_id"] == "revision-1"
            assert data["task_id"] == "task-1"
        assert current_trace_context().production_id is None

    assert current_trace_context().trace_id is None


def test_unknown_context_fields_are_ignored() -> None:
    with start_trace("trace-2"):
        with bind_trace_context(production_id="p", user_id="must-not-propagate"):
            context = current_trace_context()
            assert context.production_id == "p"
            assert not hasattr(context, "user_id")
