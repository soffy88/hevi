"""Deterministic, staging-only OpenAI-compatible fake provider.

This module is an independently runnable ASGI service.  It is not imported by
``hevi.api.main`` and it never makes outbound requests.  The service is enabled
only when both of these runtime values are explicit::

    HEVI_DEPLOY_ENV=staging
    HEVI_FAKE_PROVIDER_ENABLED=true

Any other combination, including production with the enable flag set, returns
404.  Scenarios are selected in the request body so qualification runs are
repeatable and do not need provider credentials.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

FakeScenario = Literal[
    "success",
    "timeout",
    "rate_limit",
    "server_error",
    "malformed",
    "slow",
    "stream_abort",
]

STAGING_ONLY = True
PRODUCTION_DEFAULT_ENABLED = False
NO_REAL_PROVIDER_FORWARDING = True
NO_SECRET_REQUIRED = True

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DEFAULT_DELAY_MS: dict[str, int] = {
    "timeout": 1_000,
    "slow": 250,
}


class FakeProviderRequest(BaseModel):
    """Small OpenAI-compatible request envelope with an explicit scenario."""

    model_config = ConfigDict(extra="forbid")

    scenario: FakeScenario = "success"
    model: str = Field(default="fake-model", min_length=1, max_length=128)
    messages: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    max_tokens: int = Field(default=64, ge=1, le=4_096)
    temperature: float | None = Field(default=None, ge=0, le=2)
    stream: bool = False
    # Qualification tests can shorten a scenario delay; the service still
    # rejects unbounded values so a bad test cannot create an endless request.
    delay_ms: int | None = Field(default=None, ge=0, le=5_000)


app = FastAPI(
    title="HEVI RC5 deterministic fake provider",
    docs_url=None,
    redoc_url=None,
)


def fake_provider_enabled() -> bool:
    """Return whether the service is explicitly enabled for staging only."""

    environment = os.getenv("HEVI_DEPLOY_ENV", "").strip().lower()
    enabled = os.getenv("HEVI_FAKE_PROVIDER_ENABLED", "false").strip().lower()
    return environment == "staging" and enabled in _TRUE_VALUES


def _require_enabled() -> None:
    # Do not disclose whether the service is disabled or running in a wrong
    # environment.  A disabled fake service is indistinguishable from absent.
    if not fake_provider_enabled():
        raise HTTPException(status_code=404, detail="not found")


async def _delay_for(request: FakeProviderRequest) -> None:
    delay_ms = request.delay_ms
    if delay_ms is None:
        delay_ms = _DEFAULT_DELAY_MS.get(request.scenario, 0)
    if delay_ms:
        await asyncio.sleep(delay_ms / 1_000)


def _success_payload(request: FakeProviderRequest) -> dict[str, Any]:
    # Fixed content and usage make evidence and metrics assertions deterministic
    # while never reflecting request messages or other caller content.
    return {
        "id": "fake-rc5-success",
        "object": "chat.completion",
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "fake-provider-success"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }


async def _interrupted_stream() -> AsyncIterator[bytes]:
    """Emit a partial SSE frame and omit the terminal marker intentionally."""

    yield b'data: {"id":"fake-rc5-stream","choices":[{"delta":{"content":"partial"}}]}\n\n'
    await asyncio.sleep(0)
    # No ``data: [DONE]`` follows: clients must treat this as an interrupted
    # stream, and the unified wrapper must not replay it as an unsafe request.


@app.get("/health")
async def health() -> dict[str, Any]:
    _require_enabled()
    return {
        "status": "ok",
        "service": "hevi-rc5-fake-provider",
        "staging_only": STAGING_ONLY,
        "production_default_enabled": PRODUCTION_DEFAULT_ENABLED,
        "no_real_provider_forwarding": NO_REAL_PROVIDER_FORWARDING,
        "no_secret_required": NO_SECRET_REQUIRED,
    }


@app.post("/v1/fake-provider/generate")
async def generate(request: FakeProviderRequest) -> Response:
    _require_enabled()

    if request.scenario == "timeout" or request.scenario == "slow":
        await _delay_for(request)

    if request.scenario == "rate_limit":
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "0"},
            content={"error": {"type": "rate_limit", "code": "fake_rate_limit"}},
        )
    if request.scenario == "server_error":
        return JSONResponse(
            status_code=500,
            content={"error": {"type": "server_error", "code": "fake_server_error"}},
        )
    if request.scenario == "malformed":
        return Response(content=b'{"choices":', media_type="application/json")
    if request.scenario == "stream_abort":
        return StreamingResponse(
            _interrupted_stream(),
            media_type="text/event-stream",
            headers={"X-Fake-Provider-Scenario": "stream_abort"},
        )
    return JSONResponse(_success_payload(request))


__all__ = [
    "NO_REAL_PROVIDER_FORWARDING",
    "NO_SECRET_REQUIRED",
    "PRODUCTION_DEFAULT_ENABLED",
    "STAGING_ONLY",
    "FakeProviderRequest",
    "app",
    "fake_provider_enabled",
]
