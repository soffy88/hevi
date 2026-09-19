"""D7-J: correlation ids, response headers, secret redaction."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.observability import bind_trace_context, current_trace_context
from hevi.observability.redaction import RedactionFilter, install_redaction_filter


def test_response_carries_correlation_headers() -> None:
    client = TestClient(app)
    response = client.get("/api/health", headers={"x-request-id": "req-123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "req-123"
    assert response.headers.get("X-Trace-ID")


def test_trace_context_binds_incident_and_run() -> None:
    with bind_trace_context(incident_id="inc-1", run_id="run-1", request_id="req-9"):
        ctx = current_trace_context()
        assert ctx.incident_id == "inc-1"
        assert ctx.run_id == "run-1"
        assert ctx.request_id == "req-9"
        fields = ctx.log_fields()
        assert fields["incident_id"] == "inc-1"


def test_redaction_filter_masks_secret() -> None:
    record = logging.LogRecord(
        name="t", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="calling provider with api_key: sk-abcdefgh12345678", args=(), exc_info=None,
    )
    assert RedactionFilter().filter(record) is True
    assert "sk-abcdefgh12345678" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_install_redaction_filter_idempotent() -> None:
    logger = logging.getLogger("d7-test")
    install_redaction_filter(logger)
    install_redaction_filter(logger)
    assert sum(isinstance(f, RedactionFilter) for f in logger.filters) == 1
