"""Shared, fail-closed execution contract for LLM/VLM providers.

RC5 deliberately keeps provider adapters thin.  This module owns the safety
properties that must be identical for Qwen, Ollama, NIM, OpenCode, Teamo,
LongCat, and future OpenAI-compatible providers:

* bounded connect/read/write/pool timeouts and an overall call deadline;
* retries only when the caller explicitly declares the operation idempotent;
* bounded exponential backoff with jitter and a finite attempt count;
* circuit breaker, non-waiting bulkhead, and request/token/cost budgets;
* redacted low-cardinality Prometheus metrics; and
* a result object that never turns a provider failure into learning evidence.

The wrapper returns ``ProviderCallResult`` for dependency failures instead of
leaking transport exceptions or response bodies.  Adapters that need to
trigger an existing fallback can call ``result.require_value()``; this raises
the typed, redacted ``ProviderCallError``.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import random
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeVar, cast

import httpx

from hevi.monitoring.metrics import (
    circuit_breaker_state,
    provider_cost_total,
    provider_errors_total,
    provider_input_tokens_total,
    provider_latency_seconds,
    provider_output_tokens_total,
    provider_requests_total,
    provider_timeouts_total,
)

T = TypeVar("T")


class ProviderErrorClass(StrEnum):
    """Stable error taxonomy used by metrics and operational policy."""

    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    NETWORK_ERROR = "network_error"
    MALFORMED_RESPONSE = "malformed_response"
    CIRCUIT_OPEN = "circuit_open"
    BULKHEAD_SATURATED = "bulkhead_saturated"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


class CircuitState(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Explicit upper bounds for one provider HTTP call."""

    connect_s: float = 5.0
    read_s: float = 30.0
    write_s: float = 10.0
    pool_s: float = 5.0
    total_s: float = 60.0

    def __post_init__(self) -> None:
        values = (self.connect_s, self.read_s, self.write_s, self.pool_s, self.total_s)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("provider timeouts must be finite positive values")
        # Keep configuration from silently turning a retrying request into a
        # multi-minute request.  Operators can raise this only by changing
        # the code-level policy and its qualification tests.
        if self.connect_s > 15 or self.read_s > 60 or self.write_s > 30 or self.pool_s > 15:
            raise ValueError("provider phase timeout exceeds RC5 safety bound")
        if self.total_s > 120:
            raise ValueError("provider total timeout exceeds RC5 safety bound")

    @property
    def httpx_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.read_s,
            connect=self.connect_s,
            read=self.read_s,
            write=self.write_s,
            pool=self.pool_s,
        )


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Per-wrapper budget; unset dimensions are represented by ``None``."""

    max_requests: int | None = 100
    max_input_tokens: int | None = 100_000
    max_output_tokens: int | None = 50_000
    max_cost_usd: float | None = 10.0

    def __post_init__(self) -> None:
        if self.max_requests is not None and self.max_requests < 1:
            raise ValueError("max_requests must be positive or None")
        for value in (self.max_input_tokens, self.max_output_tokens):
            if value is not None and value < 0:
                raise ValueError("token budgets must be non-negative or None")
        if self.max_cost_usd is not None and self.max_cost_usd < 0:
            raise ValueError("cost budget must be non-negative or None")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Finite retry policy.  Retrying is still opt-in per request."""

    max_attempts: int = 3
    base_backoff_s: float = 0.25
    max_backoff_s: float = 2.0
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 3:
            raise ValueError("RC5 max_attempts must be between 1 and 3")
        if self.base_backoff_s < 0 or self.max_backoff_s < 0:
            raise ValueError("backoff values must be non-negative")
        if self.base_backoff_s > self.max_backoff_s:
            raise ValueError("base backoff cannot exceed max backoff")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Per-wrapper request rate limit.

    ``None`` is useful for deterministic tests.  Configured limits reject
    immediately when no slot is available, avoiding an unbounded queue that
    could defeat the overall timeout contract.
    """

    requests_per_minute: float | None = None
    burst: int = 1

    def __post_init__(self) -> None:
        if self.requests_per_minute is not None and (
            not math.isfinite(self.requests_per_minute) or self.requests_per_minute <= 0
        ):
            raise ValueError("requests_per_minute must be finite and positive or None")
        if self.burst < 1:
            raise ValueError("burst must be positive")


@dataclass(frozen=True, slots=True)
class ReliabilityConfig:
    timeout: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    max_concurrency: int = 8
    circuit_failure_threshold: int = 3
    circuit_recovery_s: float = 15.0
    rate_limit: RateLimitPolicy = field(default_factory=RateLimitPolicy)
    budget: BudgetLimits = field(default_factory=BudgetLimits)

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.circuit_failure_threshold < 1:
            raise ValueError("circuit failure threshold must be positive")
        if self.circuit_recovery_s <= 0 or not math.isfinite(self.circuit_recovery_s):
            raise ValueError("circuit recovery must be finite and positive")


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderCallResult[T]:
    """Terminal provider result, safe to pass across the learning boundary."""

    ok: bool
    value: T | None = None
    error_class: ProviderErrorClass | None = None
    attempts: int = 0
    latency_s: float = 0.0
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    evidence_eligible: bool = False

    def require_value(self) -> T:
        if not self.ok or self.value is None:
            raise ProviderCallError(
                self.error_class or ProviderErrorClass.UNKNOWN,
                attempts=self.attempts,
            )
        return self.value


class ProviderCallError(RuntimeError):
    """Redacted adapter-facing error; never includes prompt/body/secret data."""

    def __init__(self, error_class: ProviderErrorClass, *, attempts: int) -> None:
        self.error_class = error_class
        self.attempts = attempts
        super().__init__(f"provider call failed: {error_class.value} after {attempts} attempt(s)")


class _HttpStatusError(Exception):
    def __init__(self, status_code: int, retry_after_s: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class _MalformedResponse(Exception):
    pass


class _BudgetError(Exception):
    pass


def _metric_state(state: CircuitState) -> float:
    return {CircuitState.CLOSED: 0.0, CircuitState.HALF_OPEN: 1.0, CircuitState.OPEN: 2.0}[state]


class CircuitBreaker:
    """Thread-safe circuit breaker with a single half-open probe."""

    def __init__(self, provider: str, *, failure_threshold: int = 3, recovery_s: float = 15.0):
        self.provider = provider
        self.failure_threshold = failure_threshold
        self.recovery_s = recovery_s
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        circuit_breaker_state.labels(provider=provider).set(0)

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self._state is CircuitState.OPEN:
                if now - self._opened_at < self.recovery_s:
                    return False
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = False
                circuit_breaker_state.labels(provider=self.provider).set(1)
            if self._state is CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    return False
                self._probe_in_flight = True
            return True

    def success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._probe_in_flight = False
            circuit_breaker_state.labels(provider=self.provider).set(0)

    def failure(self, error_class: ProviderErrorClass) -> None:
        # Configuration/client errors should not take the provider out for all
        # callers. Dependency failures and malformed dependency responses do.
        counted = error_class in {
            ProviderErrorClass.CONNECT_TIMEOUT,
            ProviderErrorClass.READ_TIMEOUT,
            ProviderErrorClass.TIMEOUT,
            ProviderErrorClass.RATE_LIMITED,
            ProviderErrorClass.SERVER_ERROR,
            ProviderErrorClass.NETWORK_ERROR,
            ProviderErrorClass.MALFORMED_RESPONSE,
        }
        if not counted:
            return
        with self._lock:
            self._probe_in_flight = False
            if self._state is CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                circuit_breaker_state.labels(provider=self.provider).set(2)
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                circuit_breaker_state.labels(provider=self.provider).set(2)


class _AsyncBulkhead:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.active = 0
        self.lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self.lock:
            if self.active >= self.capacity:
                return False
            self.active += 1
            return True

    async def release(self) -> None:
        async with self.lock:
            self.active -= 1


class _SyncBulkhead:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.active = 0
        self.lock = threading.Lock()

    def acquire(self) -> bool:
        with self.lock:
            if self.active >= self.capacity:
                return False
            self.active += 1
            return True

    def release(self) -> None:
        with self.lock:
            self.active -= 1


class _RequestRateLimiter:
    """Fixed-spacing, non-blocking limiter shared by async and sync paths."""

    def __init__(self, policy: RateLimitPolicy) -> None:
        self._rate_per_s = (
            policy.requests_per_minute / 60.0
            if policy.requests_per_minute is not None
            else None
        )
        self._capacity = policy.burst
        self._tokens = float(policy.burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        if self._rate_per_s is None:
            return True
        with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self._last_refill)
            self._last_refill = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_s)
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True


class _BudgetLedger:
    def __init__(self, limits: BudgetLimits):
        self.limits = limits
        self.lock = threading.Lock()
        self.requests = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def reserve(self, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        if min(input_tokens, output_tokens, cost_usd) < 0:
            raise ValueError("budget values cannot be negative")
        with self.lock:
            if self.limits.max_requests is not None and self.requests + 1 > self.limits.max_requests:
                raise _BudgetError
            if (
                self.limits.max_input_tokens is not None
                and self.input_tokens + input_tokens > self.limits.max_input_tokens
            ):
                raise _BudgetError
            if (
                self.limits.max_output_tokens is not None
                and self.output_tokens + output_tokens > self.limits.max_output_tokens
            ):
                raise _BudgetError
            if (
                self.limits.max_cost_usd is not None
                and self.cost_usd + cost_usd > self.limits.max_cost_usd
            ):
                raise _BudgetError
            self.requests += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.cost_usd += cost_usd

    def settle(
        self,
        reserved_input: int,
        reserved_output: int,
        reserved_cost: float,
        usage: ProviderUsage,
    ) -> bool:
        with self.lock:
            input_tokens = self.input_tokens + usage.input_tokens - reserved_input
            output_tokens = self.output_tokens + usage.output_tokens - reserved_output
            cost_usd = self.cost_usd + usage.cost_usd - reserved_cost
            within_budget = (
                (self.limits.max_input_tokens is None or input_tokens <= self.limits.max_input_tokens)
                and (self.limits.max_output_tokens is None or output_tokens <= self.limits.max_output_tokens)
                and (self.limits.max_cost_usd is None or cost_usd <= self.limits.max_cost_usd)
            )
            # Account for observed usage even when it breaches the preflight
            # estimate.  This fail-closed state prevents another request from
            # being admitted after a provider returned an over-budget payload.
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens
            self.cost_usd = cost_usd
            return within_budget


def estimate_input_tokens(payload: Any) -> int:
    """Conservative, content-free token estimate for preflight budgeting."""

    if isinstance(payload, str):
        return max(1, math.ceil(len(payload) / 4))
    if isinstance(payload, Mapping):
        return sum(estimate_input_tokens(key) + estimate_input_tokens(value) for key, value in payload.items())
    if isinstance(payload, (list, tuple)):
        return sum(estimate_input_tokens(item) for item in payload)
    return 0


def usage_from_payload(payload: Any, *, cost_per_1k_input: float, cost_per_1k_output: float) -> ProviderUsage:
    usage = payload.get("usage", {}) if isinstance(payload, Mapping) else {}
    if not isinstance(usage, Mapping):
        usage = {}
    input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    cost = float(
        usage.get("cost_usd", 0.0)
        or (input_tokens / 1000 * cost_per_1k_input)
        + (output_tokens / 1000 * cost_per_1k_output)
    )
    if min(input_tokens, output_tokens, cost) < 0:
        raise ValueError("provider usage cannot be negative")
    return ProviderUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost)


def _classify_exception(exc: Exception) -> tuple[ProviderErrorClass, float | None]:
    if isinstance(exc, _HttpStatusError):
        if exc.status_code == 429:
            return ProviderErrorClass.RATE_LIMITED, exc.retry_after_s
        if 500 <= exc.status_code <= 599:
            return ProviderErrorClass.SERVER_ERROR, None
        if 400 <= exc.status_code <= 499:
            return ProviderErrorClass.CLIENT_ERROR, None
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 429:
            return ProviderErrorClass.RATE_LIMITED, None
        if 500 <= status_code <= 599:
            return ProviderErrorClass.SERVER_ERROR, None
        if 400 <= status_code <= 499:
            return ProviderErrorClass.CLIENT_ERROR, None
    if isinstance(exc, httpx.ConnectTimeout):
        return ProviderErrorClass.CONNECT_TIMEOUT, None
    if isinstance(exc, httpx.ReadTimeout):
        return ProviderErrorClass.READ_TIMEOUT, None
    if isinstance(exc, httpx.TimeoutException):
        return ProviderErrorClass.TIMEOUT, None
    if isinstance(exc, TimeoutError):
        # This is the wrapper's overall deadline (or a provider SDK's generic
        # timeout), rather than a transport-specific phase timeout.
        return ProviderErrorClass.TIMEOUT, None
    if isinstance(exc, httpx.TransportError):
        return ProviderErrorClass.NETWORK_ERROR, None
    if isinstance(exc, _MalformedResponse):
        return ProviderErrorClass.MALFORMED_RESPONSE, None
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return ProviderErrorClass.MALFORMED_RESPONSE, None
    if isinstance(exc, _BudgetError):
        return ProviderErrorClass.BUDGET_EXCEEDED, None
    return ProviderErrorClass.UNKNOWN, None


_RETRYABLE_ERRORS = {
    ProviderErrorClass.CONNECT_TIMEOUT,
    ProviderErrorClass.READ_TIMEOUT,
    ProviderErrorClass.TIMEOUT,
    ProviderErrorClass.RATE_LIMITED,
    ProviderErrorClass.SERVER_ERROR,
    ProviderErrorClass.NETWORK_ERROR,
    ProviderErrorClass.MALFORMED_RESPONSE,
}


class ProviderExecutionWrapper:
    """One common reliability/metrics contract for a provider/model pair."""

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        config: ReliabilityConfig | None = None,
        async_client: httpx.AsyncClient | None = None,
        sync_client: httpx.Client | None = None,
        cost_per_1k_input: float = 0.0,
        cost_per_1k_output: float = 0.0,
    ) -> None:
        self.provider = provider
        self.model = model or "unknown"
        self.config = config or ReliabilityConfig()
        self.async_client = async_client
        self.sync_client = sync_client
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self.breaker = CircuitBreaker(
            provider,
            failure_threshold=self.config.circuit_failure_threshold,
            recovery_s=self.config.circuit_recovery_s,
        )
        self._async_bulkhead = _AsyncBulkhead(self.config.max_concurrency)
        self._sync_bulkhead = _SyncBulkhead(self.config.max_concurrency)
        self._rate_limiter = _RequestRateLimiter(self.config.rate_limit)
        self.budget = _BudgetLedger(self.config.budget)

    def _record(
        self,
        *,
        outcome: str,
        error_class: ProviderErrorClass | None,
        latency_s: float,
        usage: ProviderUsage,
    ) -> None:
        provider_requests_total.labels(
            provider=self.provider, model=self.model, outcome=outcome
        ).inc()
        provider_latency_seconds.labels(provider=self.provider, model=self.model).observe(latency_s)
        provider_input_tokens_total.labels(provider=self.provider, model=self.model).inc(
            usage.input_tokens
        )
        provider_output_tokens_total.labels(provider=self.provider, model=self.model).inc(
            usage.output_tokens
        )
        provider_cost_total.labels(provider=self.provider, model=self.model).inc(usage.cost_usd)
        if error_class is not None:
            provider_errors_total.labels(
                provider=self.provider, error_class=error_class.value
            ).inc()
            if error_class in {
                ProviderErrorClass.CONNECT_TIMEOUT,
                ProviderErrorClass.READ_TIMEOUT,
                ProviderErrorClass.TIMEOUT,
            }:
                provider_timeouts_total.labels(provider=self.provider).inc()

    def _budget_values(
        self,
        *,
        input_tokens: int,
        output_token_budget: int,
        estimated_cost_usd: float,
    ) -> tuple[int, int, float]:
        return input_tokens, output_token_budget, estimated_cost_usd + (
            output_token_budget / 1000 * self.cost_per_1k_output
        )

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        idempotent: bool,
        input_tokens: int = 0,
        output_token_budget: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> ProviderCallResult[T]:
        started = time.monotonic()
        reserved = self._budget_values(
            input_tokens=input_tokens,
            output_token_budget=output_token_budget,
            estimated_cost_usd=estimated_cost_usd,
        )
        try:
            self.budget.reserve(*reserved)
        except _BudgetError:
            result = ProviderCallResult[T](
                ok=False,
                error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result

        if not self.breaker.allow():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False,
                error_class=ProviderErrorClass.CIRCUIT_OPEN,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.CIRCUIT_OPEN.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result

        if not self._rate_limiter.try_acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False,
                error_class=ProviderErrorClass.RATE_LIMITED,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.RATE_LIMITED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result

        if not await self._async_bulkhead.acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False,
                error_class=ProviderErrorClass.BULKHEAD_SATURATED,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.BULKHEAD_SATURATED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result

        try:
            return await self._execute_async(
                operation,
                idempotent=idempotent,
                reserved=reserved,
                started=started,
            )
        finally:
            await self._async_bulkhead.release()

    async def _execute_async(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        idempotent: bool,
        reserved: tuple[int, int, float],
        started: float,
    ) -> ProviderCallResult[T]:
        last_error = ProviderErrorClass.UNKNOWN
        deadline = started + self.config.timeout.total_s
        for attempt in range(1, self.config.retry.max_attempts + 1):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.ReadTimeout("provider total timeout", request=None)
                value = await asyncio.wait_for(operation(), timeout=remaining)
                usage = usage_from_payload(
                    value,
                    cost_per_1k_input=self.cost_per_1k_input,
                    cost_per_1k_output=self.cost_per_1k_output,
                )
                if not self.budget.settle(*reserved, usage):
                    self.breaker.success()
                    result: ProviderCallResult[T] = ProviderCallResult(
                        ok=False,
                        error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                        attempts=attempt,
                        latency_s=time.monotonic() - started,
                        usage=usage,
                        evidence_eligible=False,
                    )
                    self._record(
                        outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                        error_class=result.error_class,
                        latency_s=result.latency_s,
                        usage=usage,
                    )
                    return result
                self.breaker.success()
                result = ProviderCallResult(
                    ok=True,
                    value=value,
                    attempts=attempt,
                    latency_s=time.monotonic() - started,
                    usage=usage,
                    evidence_eligible=True,
                )
                self._record(
                    outcome="success", error_class=None, latency_s=result.latency_s, usage=usage
                )
                return result
            except Exception as exc:  # dependency boundary: classify, redact, degrade
                last_error, retry_after = _classify_exception(exc)
                if not idempotent or attempt >= self.config.retry.max_attempts:
                    break
                if last_error not in _RETRYABLE_ERRORS:
                    break
                delay = retry_after if retry_after is not None else self._backoff(attempt)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(delay, remaining))
        self.breaker.failure(last_error)
        self.budget.settle(*reserved, ProviderUsage())
        result = ProviderCallResult[T](
            ok=False,
            error_class=last_error,
            attempts=attempt,
            latency_s=time.monotonic() - started,
            evidence_eligible=False,
        )
        self._record(
            outcome=last_error.value, error_class=last_error, latency_s=result.latency_s, usage=ProviderUsage()
        )
        return result

    def _backoff(self, attempt: int) -> float:
        base = min(
            self.config.retry.max_backoff_s,
            self.config.retry.base_backoff_s * (2 ** (attempt - 1)),
        )
        return float(
            base
            * (1 + random.uniform(-self.config.retry.jitter_ratio, self.config.retry.jitter_ratio))
        )

    def execute_sync(
        self,
        operation: Callable[[], T],
        *,
        idempotent: bool,
        input_tokens: int = 0,
        output_token_budget: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> ProviderCallResult[T]:
        """Synchronous twin used by legacy sync-compatible provider adapters."""

        started = time.monotonic()
        reserved = self._budget_values(
            input_tokens=input_tokens,
            output_token_budget=output_token_budget,
            estimated_cost_usd=estimated_cost_usd,
        )
        try:
            self.budget.reserve(*reserved)
        except _BudgetError:
            result = ProviderCallResult[T](
                ok=False, error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self.breaker.allow():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False, error_class=ProviderErrorClass.CIRCUIT_OPEN,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=ProviderErrorClass.CIRCUIT_OPEN.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self._rate_limiter.try_acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False,
                error_class=ProviderErrorClass.RATE_LIMITED,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.RATE_LIMITED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self._sync_bulkhead.acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False, error_class=ProviderErrorClass.BULKHEAD_SATURATED,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=ProviderErrorClass.BULKHEAD_SATURATED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result

        last_error = ProviderErrorClass.UNKNOWN
        deadline = started + self.config.timeout.total_s
        try:
            for attempt in range(1, self.config.retry.max_attempts + 1):
                try:
                    if time.monotonic() >= deadline:
                        raise httpx.ReadTimeout("provider total timeout", request=None)
                    value = operation()
                    usage = usage_from_payload(
                        value,
                        cost_per_1k_input=self.cost_per_1k_input,
                        cost_per_1k_output=self.cost_per_1k_output,
                    )
                    if not self.budget.settle(*reserved, usage):
                        self.breaker.success()
                        result = ProviderCallResult(
                            ok=False,
                            error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                            attempts=attempt,
                            latency_s=time.monotonic() - started,
                            usage=usage,
                            evidence_eligible=False,
                        )
                        self._record(
                            outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                            error_class=result.error_class,
                            latency_s=result.latency_s,
                            usage=usage,
                        )
                        return result
                    self.breaker.success()
                    result = ProviderCallResult(
                        ok=True,
                        value=value,
                        attempts=attempt,
                        latency_s=time.monotonic() - started,
                        usage=usage,
                        evidence_eligible=True,
                    )
                    self._record(
                        outcome="success", error_class=None, latency_s=result.latency_s, usage=usage
                    )
                    return result
                except Exception as exc:
                    last_error, retry_after = _classify_exception(exc)
                    if not idempotent or attempt >= self.config.retry.max_attempts or last_error not in _RETRYABLE_ERRORS:
                        break
                    delay = retry_after if retry_after is not None else self._backoff(attempt)
                    if time.monotonic() + delay >= deadline:
                        break
                    time.sleep(delay)
            self.breaker.failure(last_error)
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T](
                ok=False,
                error_class=last_error,
                attempts=attempt,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=last_error.value,
                error_class=last_error,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        finally:
            self._sync_bulkhead.release()

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        idempotent: bool,
        parser: Callable[[Any], T] | None = None,
        input_tokens: int | None = None,
        output_token_budget: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> ProviderCallResult[T | Any]:
        payload_tokens = estimate_input_tokens(json_body) if input_tokens is None else input_tokens

        async def operation() -> Any:
            client = self.async_client
            owned = client is None
            if owned:
                client = httpx.AsyncClient(
                    trust_env=True, follow_redirects=True, timeout=self.config.timeout.httpx_timeout
                )
            assert client is not None
            try:
                response = await client.request(
                    method,
                    url,
                    headers=dict(headers or {}),
                    json=json_body,
                    timeout=self.config.timeout.httpx_timeout,
                )
                if response.status_code >= 400:
                    retry_after: float | None = None
                    raw_retry_after = response.headers.get("retry-after")
                    if raw_retry_after:
                        try:
                            retry_after = max(
                                0.0, min(float(raw_retry_after), self.config.retry.max_backoff_s)
                            )
                        except ValueError:
                            retry_after = None
                    raise _HttpStatusError(response.status_code, retry_after)
                try:
                    data = response.json()
                except (ValueError, TypeError) as exc:
                    raise _MalformedResponse from exc
                if parser is not None:
                    try:
                        return parser(data)
                    except Exception as exc:
                        raise _MalformedResponse from exc
                if not isinstance(data, (dict, list)):
                    raise _MalformedResponse
                return data
            finally:
                if owned:
                    await client.aclose()

        return await self.execute(
            operation,
            idempotent=idempotent,
            input_tokens=payload_tokens,
            output_token_budget=output_token_budget,
            estimated_cost_usd=estimated_cost_usd,
        )

    def request_json_sync(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
        idempotent: bool,
        parser: Callable[[Any], T] | None = None,
        input_tokens: int | None = None,
        output_token_budget: int = 0,
        estimated_cost_usd: float = 0.0,
    ) -> ProviderCallResult[T | Any]:
        started = time.monotonic()
        payload_tokens = estimate_input_tokens(json_body) if input_tokens is None else input_tokens
        reserved = self._budget_values(
            input_tokens=payload_tokens,
            output_token_budget=output_token_budget,
            estimated_cost_usd=estimated_cost_usd,
        )
        try:
            self.budget.reserve(*reserved)
        except _BudgetError:
            result = ProviderCallResult[T | Any](
                ok=False,
                error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self.breaker.allow():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T | Any](
                ok=False, error_class=ProviderErrorClass.CIRCUIT_OPEN, latency_s=time.monotonic() - started
            )
            self._record(
                outcome=ProviderErrorClass.CIRCUIT_OPEN.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self._rate_limiter.try_acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T | Any](
                ok=False,
                error_class=ProviderErrorClass.RATE_LIMITED,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=ProviderErrorClass.RATE_LIMITED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        if not self._sync_bulkhead.acquire():
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T | Any](
                ok=False,
                error_class=ProviderErrorClass.BULKHEAD_SATURATED,
                latency_s=time.monotonic() - started,
            )
            self._record(
                outcome=ProviderErrorClass.BULKHEAD_SATURATED.value,
                error_class=result.error_class,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        try:
            client = self.sync_client
            owned = client is None
            if owned:
                client = httpx.Client(
                    trust_env=True, follow_redirects=True, timeout=self.config.timeout.httpx_timeout
                )
            assert client is not None
            last_error = ProviderErrorClass.UNKNOWN
            deadline = started + self.config.timeout.total_s
            for attempt in range(1, self.config.retry.max_attempts + 1):
                try:
                    if time.monotonic() >= deadline:
                        raise httpx.ReadTimeout("provider total timeout", request=None)
                    response = client.request(
                        method,
                        url,
                        headers=dict(headers or {}),
                        json=json_body,
                        timeout=self.config.timeout.httpx_timeout,
                    )
                    if response.status_code >= 400:
                        retry_after: float | None = None
                        raw_retry_after = response.headers.get("retry-after")
                        if raw_retry_after:
                            with contextlib.suppress(ValueError):
                                retry_after = max(
                                    0.0, min(float(raw_retry_after), self.config.retry.max_backoff_s)
                                )
                        raise _HttpStatusError(response.status_code, retry_after)
                    try:
                        data = response.json()
                    except (ValueError, TypeError) as exc:
                        raise _MalformedResponse from exc
                    if not isinstance(data, (dict, list)):
                        raise _MalformedResponse
                    if parser is not None:
                        try:
                            value = parser(data)
                        except Exception as exc:
                            raise _MalformedResponse from exc
                    else:
                        value = cast(T | Any, data)
                    usage = usage_from_payload(
                        data,
                        cost_per_1k_input=self.cost_per_1k_input,
                        cost_per_1k_output=self.cost_per_1k_output,
                    )
                    if not self.budget.settle(*reserved, usage):
                        self.breaker.success()
                        result = ProviderCallResult(
                            ok=False,
                            error_class=ProviderErrorClass.BUDGET_EXCEEDED,
                            attempts=attempt,
                            latency_s=time.monotonic() - started,
                            usage=usage,
                            evidence_eligible=False,
                        )
                        self._record(
                            outcome=ProviderErrorClass.BUDGET_EXCEEDED.value,
                            error_class=result.error_class,
                            latency_s=result.latency_s,
                            usage=usage,
                        )
                        return result
                    self.breaker.success()
                    result = ProviderCallResult(
                        ok=True,
                        value=value,
                        attempts=attempt,
                        latency_s=time.monotonic() - started,
                        usage=usage,
                        evidence_eligible=True,
                    )
                    self._record(
                        outcome="success", error_class=None, latency_s=result.latency_s, usage=usage
                    )
                    return result
                except Exception as exc:
                    last_error, retry_after = _classify_exception(exc)
                    if not idempotent or attempt >= self.config.retry.max_attempts or last_error not in _RETRYABLE_ERRORS:
                        break
                    delay = retry_after if retry_after is not None else self._backoff(attempt)
                    if time.monotonic() + delay >= deadline:
                        break
                    time.sleep(delay)
            self.breaker.failure(last_error)
            self.budget.settle(*reserved, ProviderUsage())
            result = ProviderCallResult[T | Any](
                ok=False,
                error_class=last_error,
                attempts=attempt,
                latency_s=time.monotonic() - started,
                evidence_eligible=False,
            )
            self._record(
                outcome=last_error.value,
                error_class=last_error,
                latency_s=result.latency_s,
                usage=ProviderUsage(),
            )
            return result
        finally:
            if owned and client is not None:
                client.close()
            self._sync_bulkhead.release()


__all__ = [
    "BudgetLimits",
    "CircuitBreaker",
    "CircuitState",
    "ProviderCallError",
    "ProviderCallResult",
    "ProviderErrorClass",
    "ProviderExecutionWrapper",
    "ProviderUsage",
    "ReliabilityConfig",
    "RetryPolicy",
    "TimeoutPolicy",
    "estimate_input_tokens",
]
