import asyncio
import logging
import random
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from hevi.resilience.errors import RetryableError, classify_error

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 2.0
    max_delay_s: float = 30.0
    jitter: bool = True


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
