"""Lightweight in-process rate limiting.

A dependency-free sliding-window limiter keyed by client IP (or authenticated
user) + scope. Protects the abuse-prone endpoints (auth brute-force/enumeration,
expensive GPU/LLM creative calls, task creation, video submission) without an
external store.

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


def _user_id(request: Request) -> str | None:
    """Best-effort authenticated-user identity for per-user buckets.

    Invalid/expired tokens fall back to the IP bucket. Rate limiting must never
    become an oracle for token validity, so decode failures are silent.
    """
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        from hevi.auth.jwt_handler import decode_access_token

        sub = decode_access_token(token.strip()).get("sub")
    except Exception:
        return None
    return str(sub) if sub else None


def rate_limit(
    scope: str,
    max_requests: int,
    window_s: float,
    per_user: bool = False,
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency enforcing max_requests per window_s.

    ``per_user=True`` keys authenticated requests by user id so one account
    cannot spread submission traffic across IPs; anonymous requests and
    endpoints where a user is not yet known stay keyed by client IP.
    """

    async def _dep(request: Request) -> None:
        if settings.debug:
            return
        user = _user_id(request) if per_user else None
        key = f"{scope}:u:{user}" if user else f"{scope}:{_client_ip(request)}"
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
