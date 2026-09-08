"""RC5 deterministic provider reliability gate.

All cases use httpx.MockTransport or local async operations; no real provider
endpoint, credential, prompt, or user data is used.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from hevi.providers.learning_gate import ProviderLearningGate
from hevi.providers.reliability import (
    BudgetLimits,
    CircuitState,
    ProviderErrorClass,
    ProviderExecutionWrapper,
    RateLimitPolicy,
    ReliabilityConfig,
    RetryPolicy,
    TimeoutPolicy,
)


def config(
    *,
    attempts: int = 2,
    concurrency: int = 4,
    threshold: int = 3,
    recovery_s: float = 1.0,
    budget: BudgetLimits | None = None,
) -> ReliabilityConfig:
    return ReliabilityConfig(
        timeout=TimeoutPolicy(connect_s=1, read_s=2, write_s=1, pool_s=1, total_s=5),
        retry=RetryPolicy(max_attempts=attempts, base_backoff_s=0, max_backoff_s=0, jitter_ratio=0),
        max_concurrency=concurrency,
        circuit_failure_threshold=threshold,
        circuit_recovery_s=recovery_s,
        rate_limit=RateLimitPolicy(None),
        budget=budget or BudgetLimits(max_requests=100, max_input_tokens=10000, max_output_tokens=10000),
    )


def response(request: httpx.Request, status: int = 200, **payload: Any) -> httpx.Response:
    return httpx.Response(status, json=payload or {"choices": [], "usage": {}}, request=request)


async def call(
    handler: Callable[[httpx.Request], httpx.Response | Exception],
    *,
    idempotent: bool = True,
    reliability: ReliabilityConfig | None = None,
    parser: Callable[[Any], Any] | None = None,
):
    def wrapped(request: httpx.Request) -> httpx.Response:
        result = handler(request)
        if isinstance(result, Exception):
            raise result
        return result

    async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
        wrapper = ProviderExecutionWrapper(
            "fake-provider",
            "fake-model",
            config=reliability or config(),
            async_client=client,
        )
        return await wrapper.request_json(
            "POST",
            "https://provider.test/v1/chat/completions",
            headers={"Authorization": "test-only"},
            json_body={"messages": [{"role": "user", "content": "fixture"}]},
            idempotent=idempotent,
            parser=parser,
            output_token_budget=8,
        )


@pytest.mark.asyncio
async def test_success_records_usage_and_is_evidence_eligible():
    result = await call(
        lambda request: response(
            request,
            choices=[{"message": {"content": "ok"}}],
            usage={"prompt_tokens": 3, "completion_tokens": 2},
        )
    )
    assert result.ok and result.evidence_eligible
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 2
    assert result.attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exception", "error_class"),
    [
        (httpx.ConnectTimeout("connect", request=None), ProviderErrorClass.CONNECT_TIMEOUT),
        (httpx.ReadTimeout("read", request=None), ProviderErrorClass.READ_TIMEOUT),
    ],
)
async def test_connect_and_read_timeout_are_bounded_and_graceful(exception, error_class):
    seen = {"count": 0}

    def handler(request):
        seen["count"] += 1
        return exception

    result = await call(handler)
    assert not result.ok
    assert result.error_class is error_class
    assert result.evidence_eligible is False
    assert seen["count"] == 2


@pytest.mark.asyncio
async def test_overall_deadline_is_bounded():
    reliability = ReliabilityConfig(
        timeout=TimeoutPolicy(connect_s=1, read_s=1, write_s=1, pool_s=1, total_s=0.02),
        retry=RetryPolicy(max_attempts=3, base_backoff_s=0, max_backoff_s=0, jitter_ratio=0),
        budget=BudgetLimits(max_requests=10, max_input_tokens=100, max_output_tokens=100),
    )
    wrapper = ProviderExecutionWrapper("deadline-provider", "model", config=reliability)

    async def hangs():
        await asyncio.sleep(1)

    result = await wrapper.execute(hangs, idempotent=True)
    assert result.error_class is ProviderErrorClass.TIMEOUT
    assert result.attempts == 1
    assert result.latency_s < 0.5


@pytest.mark.asyncio
async def test_retryable_5xx_retries_only_idempotent_request():
    seen = {"count": 0}

    def handler(request):
        seen["count"] += 1
        return response(request, 500) if seen["count"] == 1 else response(
            request, choices=[{"message": {"content": "ok"}}], usage={}
        )

    result = await call(handler, idempotent=True)
    assert result.ok and result.attempts == 2

    seen["count"] = 0
    result = await call(handler, idempotent=False)
    assert not result.ok and result.error_class is ProviderErrorClass.SERVER_ERROR
    assert result.attempts == 1 and seen["count"] == 1


@pytest.mark.asyncio
async def test_wrapper_rate_limit_is_bounded_and_fail_closed():
    reliability = config()
    reliability = ReliabilityConfig(
        timeout=reliability.timeout,
        retry=reliability.retry,
        max_concurrency=reliability.max_concurrency,
        circuit_failure_threshold=reliability.circuit_failure_threshold,
        circuit_recovery_s=reliability.circuit_recovery_s,
        rate_limit=RateLimitPolicy(requests_per_minute=60),
        budget=reliability.budget,
    )
    wrapper = ProviderExecutionWrapper("rate-provider", "model", config=reliability)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"usage": {}}

    first = await wrapper.execute(operation, idempotent=True)
    second = await wrapper.execute(operation, idempotent=True)
    assert first.ok
    assert not second.ok
    assert second.error_class is ProviderErrorClass.RATE_LIMITED
    assert calls == 1


@pytest.mark.asyncio
async def test_429_is_bounded_and_non_retryable_4xx_is_not_retried():
    seen = {"count": 0}

    def limited(request):
        seen["count"] += 1
        return httpx.Response(429, headers={"retry-after": "0"}, request=request)

    result = await call(limited)
    assert not result.ok and result.error_class is ProviderErrorClass.RATE_LIMITED
    assert result.attempts == 2 and seen["count"] == 2

    seen["count"] = 0
    result = await call(lambda request: response(request, 400))
    assert not result.ok and result.error_class is ProviderErrorClass.CLIENT_ERROR
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_malformed_response_never_becomes_evidence():
    result = await call(
        lambda request: httpx.Response(200, text="not-json", request=request),
        reliability=config(attempts=1),
    )
    assert not result.ok
    assert result.error_class is ProviderErrorClass.MALFORMED_RESPONSE
    assert result.evidence_eligible is False


@pytest.mark.asyncio
async def test_circuit_open_half_open_and_recovery():
    seen = {"count": 0}
    mode = {"healthy": False}

    def handler(request):
        seen["count"] += 1
        if not mode["healthy"]:
            return response(request, 503)
        return response(request, choices=[{"message": {"content": "recovered"}}], usage={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        wrapper = ProviderExecutionWrapper(
            "circuit-provider", "model", config=config(attempts=1, threshold=2), async_client=client
        )
        for _ in range(2):
            result = await wrapper.request_json("GET", "https://provider.test/health", idempotent=True)
            assert result.error_class is ProviderErrorClass.SERVER_ERROR
        assert wrapper.breaker.state is CircuitState.OPEN
        result = await wrapper.request_json("GET", "https://provider.test/health", idempotent=True)
        assert result.error_class is ProviderErrorClass.CIRCUIT_OPEN
        assert seen["count"] == 2

        wrapper.breaker._opened_at -= 2  # deterministic clock advance for the fake test
        mode["healthy"] = True
        result = await wrapper.request_json("GET", "https://provider.test/health", idempotent=True)
        assert result.ok
        assert wrapper.breaker.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_bulkhead_rejects_saturation_without_waiting():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def operation():
        entered.set()
        await release.wait()
        return {"choices": [], "usage": {}}

    wrapper = ProviderExecutionWrapper(
        "bulkhead-provider", "model", config=config(attempts=1, concurrency=1)
    )
    first = asyncio.create_task(wrapper.execute(operation, idempotent=True))
    await entered.wait()
    second = await wrapper.execute(operation, idempotent=True)
    assert second.error_class is ProviderErrorClass.BULKHEAD_SATURATED
    release.set()
    assert (await first).ok


@pytest.mark.asyncio
async def test_request_token_and_cost_budgets_fail_closed():
    limits = BudgetLimits(max_requests=1, max_input_tokens=100, max_output_tokens=8, max_cost_usd=0.01)
    reliability = config(attempts=1, budget=limits)
    wrapper = ProviderExecutionWrapper("budget-provider", "model", config=reliability)

    async def successful_response():
        return {"usage": {"prompt_tokens": 1}}

    first = await wrapper.execute(
        successful_response, idempotent=True, estimated_cost_usd=0.001
    )
    second = await wrapper.execute(successful_response, idempotent=True)
    assert first.ok and second.error_class is ProviderErrorClass.BUDGET_EXCEEDED

    cost_limited = ProviderExecutionWrapper(
        "cost-provider", "model", config=config(
            attempts=1,
            budget=BudgetLimits(max_requests=10, max_input_tokens=100, max_output_tokens=100, max_cost_usd=0.001),
        )
    )
    async def empty_response():
        return {"usage": {}}

    cost_rejected = await cost_limited.execute(
        empty_response, idempotent=True, estimated_cost_usd=0.002
    )
    assert cost_rejected.error_class is ProviderErrorClass.BUDGET_EXCEEDED

    token_limited = ProviderExecutionWrapper(
        "token-provider",
        "model",
        config=config(
            attempts=1,
            budget=BudgetLimits(max_requests=10, max_input_tokens=1, max_output_tokens=1, max_cost_usd=0.001),
        ),
    )
    rejected = await token_limited.execute(
        empty_response, idempotent=True, input_tokens=2, output_token_budget=0
    )
    assert rejected.error_class is ProviderErrorClass.BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_duplicate_retry_does_not_duplicate_evidence_or_fsrs():
    result = ProviderExecutionWrapper(
        "learning-provider", "model", config=config(attempts=2)
    )
    state = {"attempts": 0}

    async def op():
        state["attempts"] += 1
        if state["attempts"] == 1:
            raise httpx.ReadTimeout("transient", request=None)
        return {"answer": "stable"}

    provider_result = await result.execute(op, idempotent=True)
    gate = ProviderLearningGate()
    calls = {"evidence": 0, "mastery": 0, "fsrs": 0}

    def evidence(value):
        calls["evidence"] += 1
        return {"value": value}

    def mastery(_evidence):
        calls["mastery"] += 1

    def fsrs(_evidence):
        calls["fsrs"] += 1

    committed = gate.commit(
        provider_result,
        operation_key="attempt-opaque-key",
        create_evidence=evidence,
        advance_mastery=mastery,
        advance_fsrs=fsrs,
    )
    duplicate = gate.commit(
        provider_result,
        operation_key="attempt-opaque-key",
        create_evidence=evidence,
        advance_mastery=mastery,
        advance_fsrs=fsrs,
    )
    assert committed.accepted and duplicate.reason == "duplicate_operation"
    assert calls == {"evidence": 1, "mastery": 1, "fsrs": 1}

    failure = ProviderExecutionWrapper("offline-provider", "model", config=config(attempts=1))
    failed_result = await failure.execute(
        lambda: (_ for _ in ()).throw(httpx.ConnectTimeout("offline", request=None)),
        idempotent=True,
    )
    rejected = gate.commit(
        failed_result,
        operation_key="offline-opaque-key",
        create_evidence=evidence,
        advance_mastery=mastery,
        advance_fsrs=fsrs,
    )
    assert not rejected.accepted
    assert calls == {"evidence": 1, "mastery": 1, "fsrs": 1}


def test_metrics_contract_has_only_low_cardinality_labels():
    from hevi.monitoring import metrics

    names = {item.name for item in metrics.provider_requests_total.collect()}
    assert "provider_requests" in names
    assert metrics.provider_requests_total._labelnames == ("provider", "model", "outcome")
    assert metrics.provider_errors_total._labelnames == ("provider", "error_class")
    assert metrics.provider_latency_seconds._labelnames == ("provider", "model")
    assert metrics.provider_input_tokens_total._labelnames == ("provider", "model")
    assert metrics.provider_output_tokens_total._labelnames == ("provider", "model")
    assert metrics.provider_cost_total._labelnames == ("provider", "model")
