import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from dataclasses import asdict, dataclass
from typing import Any

from hevi.resilience.errors import RetryableError, classify_error

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 2.0
    max_delay_s: float = 30.0
    jitter: bool = True


@dataclass
class RetryEvidence:
    """Redacted, serializable evidence for one idempotent runtime operation."""

    retry_supported: bool = True
    retry_exercised: bool = False
    operation_id: str = ""
    idempotency_key: str = ""
    attempt_count: int = 0
    failure_class: str | None = None
    retryable: bool = False
    backoff_policy: dict[str, Any] | None = None
    first_attempt_result: str = ""
    final_attempt_result: str = ""
    side_effect_duplicate_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def with_retry_evidence[T](
    coro_factory: Callable[[int], Coroutine[Any, Any, T]],
    *,
    operation_id: str,
    idempotency_key: str,
    policy: RetryPolicy | None = None,
) -> tuple[T, RetryEvidence]:
    """Run an idempotent operation and return production retry evidence."""

    p = policy or RetryPolicy()
    evidence = RetryEvidence(
        operation_id=operation_id,
        idempotency_key=idempotency_key,
        backoff_policy={
            "max_attempts": p.max_attempts,
            "initial_backoff_s": p.base_delay_s,
            "max_backoff_s": p.max_delay_s,
            "jitter": p.jitter,
        },
    )
    for attempt in range(1, p.max_attempts + 1):
        evidence.attempt_count = attempt
        try:
            value = await coro_factory(attempt)
        except Exception as exc:
            classified = classify_error(exc)
            evidence.failure_class = type(classified).__name__
            evidence.retryable = isinstance(classified, RetryableError)
            evidence.first_attempt_result = evidence.first_attempt_result or "failed"
            if not evidence.retryable or attempt >= p.max_attempts:
                evidence.final_attempt_result = "failed"
                raise
            evidence.retry_exercised = True
            delay = min(p.base_delay_s * (2 ** (attempt - 1)), p.max_delay_s)
            if p.jitter:
                delay *= 0.5 + random.random()
            await asyncio.sleep(delay)
        else:
            evidence.first_attempt_result = evidence.first_attempt_result or "completed"
            evidence.final_attempt_result = "completed"
            return value, evidence
    raise RuntimeError("retry loop exited without result")


async def with_retry[T](
    coro_factory: Callable[[], Coroutine[Any, Any, T]],
    policy: RetryPolicy | None = None,
) -> T:
    """Execute a coroutine with exponential backoff and jitter.

    Args:
        coro_factory: A function that returns a new coroutine object each time it's called.
        policy: The retry configuration. Defaults to RetryPolicy().

    Returns:
        T: The result of the coroutine.

    Raises:
        Exception: The last exception caught if all retries fail, or the first unretryable error.
    """
    p = policy or RetryPolicy()
    last_exc: Exception | None = None

    for attempt in range(1, p.max_attempts + 1):
        try:
            # Re-create coroutine on each attempt (prevents 'already awaited' errors)
            return await coro_factory()
        except Exception as e:
            classified = classify_error(e)
            if not isinstance(classified, RetryableError):
                logger.error(f"Unretryable error on attempt {attempt}: {e}")
                raise e

            last_exc = e
            if attempt == p.max_attempts:
                logger.error(f"Max retry attempts ({p.max_attempts}) reached. Last error: {e}")
                break

            # Calculate delay: base_delay * 2^(attempt-1)
            delay = min(p.base_delay_s * (2 ** (attempt - 1)), p.max_delay_s)
            if p.jitter:
                delay *= 0.5 + random.random()

            logger.warning(
                f"Retryable error on attempt {attempt}/{p.max_attempts}: {e}. "
                f"Retrying in {delay:.2f}s..."
            )
            await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("Retry loop exited without result or exception")
