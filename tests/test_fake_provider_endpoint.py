"""RC5 deterministic HTTP fake-provider qualification contract."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from hevi.providers.reliability import (
    BudgetLimits,
    ProviderErrorClass,
    ProviderExecutionWrapper,
    RateLimitPolicy,
    ReliabilityConfig,
    RetryPolicy,
    TimeoutPolicy,
)
from hevi.staging import fake_provider


def _config(*, attempts: int = 1, total_s: float = 1.0) -> ReliabilityConfig:
    return ReliabilityConfig(
        timeout=TimeoutPolicy(
            connect_s=0.1,
            read_s=0.1,
            write_s=0.1,
            pool_s=0.1,
            total_s=total_s,
        ),
        retry=RetryPolicy(max_attempts=attempts, base_backoff_s=0, max_backoff_s=0, jitter_ratio=0),
        max_concurrency=2,
        circuit_failure_threshold=2,
        circuit_recovery_s=0.01,
        rate_limit=RateLimitPolicy(None),
        budget=BudgetLimits(max_requests=20, max_input_tokens=10_000, max_output_tokens=10_000),
    )


def _parse_chat_completion(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("response has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not message.get("content"):
        raise ValueError("response has no message content")
    return payload


async def _wrapped_call(
    client: httpx.AsyncClient,
    scenario: str,
    *,
    attempts: int = 1,
    total_s: float = 1.0,
    idempotent: bool = True,
    delay_ms: int | None = None,
) -> Any:
    wrapper = ProviderExecutionWrapper(
        "fake-provider",
        "fake-model",
        config=_config(attempts=attempts, total_s=total_s),
        async_client=client,
    )
    body: dict[str, Any] = {"scenario": scenario, "messages": [{"role": "user", "content": "fixture"}]}
    if delay_ms is not None:
        body["delay_ms"] = delay_ms
    return await wrapper.request_json(
        "POST",
        "/v1/fake-provider/generate",
        json_body=body,
        idempotent=idempotent,
        parser=_parse_chat_completion,
        output_token_budget=16,
    )


@pytest.fixture
async def fake_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("HEVI_DEPLOY_ENV", "staging")
    monkeypatch.setenv("HEVI_FAKE_PROVIDER_ENABLED", "true")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fake_provider.app), base_url="http://fake"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_fake_success_passes_unified_wrapper(fake_client: httpx.AsyncClient) -> None:
    result = await _wrapped_call(fake_client, "success")
    assert result.ok and result.evidence_eligible
    assert result.value["choices"][0]["message"]["content"] == "fake-provider-success"
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens == 2
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_fake_timeout_is_bounded_and_not_evidence(fake_client: httpx.AsyncClient) -> None:
    started = time.monotonic()
    result = await _wrapped_call(fake_client, "timeout", total_s=0.02, delay_ms=100)
    assert result.error_class is ProviderErrorClass.TIMEOUT
    assert result.evidence_eligible is False
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_fake_429_uses_finite_retry(fake_client: httpx.AsyncClient) -> None:
    result = await _wrapped_call(fake_client, "rate_limit", attempts=2)
    assert result.error_class is ProviderErrorClass.RATE_LIMITED
    assert result.attempts == 2
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_fake_500_uses_finite_retry_and_circuit_contract(
    fake_client: httpx.AsyncClient,
) -> None:
    result = await _wrapped_call(fake_client, "server_error", attempts=2)
    assert result.error_class is ProviderErrorClass.SERVER_ERROR
    assert result.attempts == 2
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_fake_malformed_is_graceful(fake_client: httpx.AsyncClient) -> None:
    result = await _wrapped_call(fake_client, "malformed")
    assert result.error_class is ProviderErrorClass.MALFORMED_RESPONSE
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_fake_slow_obeys_total_deadline(fake_client: httpx.AsyncClient) -> None:
    result = await _wrapped_call(fake_client, "slow", total_s=0.02, delay_ms=100)
    assert result.error_class is ProviderErrorClass.TIMEOUT
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_fake_stream_abort_is_not_retried(fake_client: httpx.AsyncClient) -> None:
    result = await _wrapped_call(fake_client, "stream_abort", idempotent=False)
    assert result.error_class is ProviderErrorClass.MALFORMED_RESPONSE
    assert result.attempts == 1
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_fake_service_is_disabled_outside_explicit_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = httpx.ASGITransport(app=fake_provider.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as client:
        monkeypatch.setenv("HEVI_DEPLOY_ENV", "production")
        monkeypatch.setenv("HEVI_FAKE_PROVIDER_ENABLED", "true")
        assert (await client.get("/health")).status_code == 404
        assert (
            await client.post("/v1/fake-provider/generate", json={"scenario": "success"})
        ).status_code == 404

        monkeypatch.setenv("HEVI_DEPLOY_ENV", "staging")
        monkeypatch.setenv("HEVI_FAKE_PROVIDER_ENABLED", "false")
        assert (await client.get("/health")).status_code == 404

        monkeypatch.setenv("HEVI_FAKE_PROVIDER_ENABLED", "true")
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["staging_only"] is True


@pytest.mark.asyncio
async def test_fake_service_never_needs_or_leaks_a_secret(
    fake_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "fake-provider-test-secret-never-log"
    monkeypatch.setenv("DASHSCOPE_API_KEY", secret)
    response = await fake_client.post(
        "/v1/fake-provider/generate",
        json={"scenario": "success", "messages": [{"role": "user", "content": secret}]},
    )
    assert response.status_code == 200
    assert secret not in response.text
    health = await fake_client.get("/health")
    assert health.json()["no_secret_required"] is True
    assert health.json()["no_real_provider_forwarding"] is True
