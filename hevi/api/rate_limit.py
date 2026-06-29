"""Lightweight in-process rate limiting.

A dependency-free sliding-window limiter keyed by client IP + scope. Protects
the abuse-prone endpoints (auth brute-force/enumeration, expensive GPU/LLM
creative calls, task creation) without an external store.

Scope/limits are per-process — matching the current single-instance worker
topology (the queue worker runs inside the app lifespan). For multi-instance
deployment this should move to a shared store (Redis); see audit backlog.

Disabled when settings.debug is true so the test/dev suites (which hammer auth
from one IP) aren't throttled.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, status

from hevi.core.config import settings

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Honor X-Forwarded-For first hop when behind a trusted proxy (nginx/cf tunnel).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str, max_requests: int, window_s: float
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency enforcing max_requests per window_s per IP."""

    async def _dep(request: Request) -> None:
        if settings.debug:
            return
        key = f"{scope}:{_client_ip(request)}"
        now = time.monotonic()
        bucket = _BUCKETS[key]
        cutoff = now - window_s
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, slow down and retry shortly",
            )
        bucket.append(now)

    return _dep
