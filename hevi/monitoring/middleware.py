"""HTTP request metrics middleware."""

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from hevi.monitoring.metrics import (
    http_request_duration_seconds,
    http_requests_in_progress,
    http_requests_total,
)
from hevi.observability import bind_trace_context, start_trace

_RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class PrometheusMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: _RequestResponseEndpoint) -> Response:
        method = request.method
        http_requests_in_progress.inc()
        start = time.perf_counter()
        trace_id = request.headers.get("x-trace-id")
        identifiers = {
            field: request.headers.get(f"x-{field.replace('_', '-')}")
            for field in (
                "production_id",
                "revision_id",
                "plan_id",
                "task_id",
                "attempt_id",
                "node_id",
                "artifact_id",
                "evaluation_id",
            )
        }
        try:
            with start_trace(trace_id), bind_trace_context(**identifiers):
                response = await call_next(request)
                duration = time.perf_counter() - start
                # Use route template after routing completes — avoids label cardinality
                # explosion (e.g. /api/video/{id})
                path_template = str(
                    getattr(request.scope.get("route"), "path", request.url.path)
                )
                status = str(response.status_code)
                http_requests_total.labels(
                    method=method, path=path_template, status=status
                ).inc()
                http_request_duration_seconds.labels(
                    method=method, path=path_template
                ).observe(duration)
                return response
        finally:
            http_requests_in_progress.dec()
