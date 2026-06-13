import logging
from collections.abc import Callable, Coroutine
from typing import Any

from hevi.observability import log_event
from hevi.resilience.retry_policy import RetryPolicy, with_retry

logger = logging.getLogger(__name__)

PROVIDER_FALLBACK = {
    "ltx2_cloud": ["ltx2_cloud", "wan_cloud"],  # ltx2 失败切 wan
    "wan_cloud": ["wan_cloud", "ltx2_cloud"],
}


async def run_with_fallback[T](
    *,
    initial_provider: str,
    runner: Callable[[str], Coroutine[Any, Any, T]],
    on_fallback: Callable[[str, str, Exception], Coroutine[Any, Any, None]],
    retry_policy: RetryPolicy | None = None,
) -> T:
    """Execute a runner function with provider-level fallback.

    Args:
        initial_provider: The first provider to try.
        runner: A function that takes a provider name and returns a result coroutine.
        on_fallback: Callback called when switching providers.
        retry_policy: Retry configuration for each provider attempt. Defaults to RetryPolicy().

    Returns:
        T: The result from the first successful provider.
    """
    p_policy = retry_policy or RetryPolicy()
    chain = PROVIDER_FALLBACK.get(initial_provider, [initial_provider])
    last_exc: Exception | None = None

    for idx, provider in enumerate(chain):
        try:
            logger.info(f"Attempting task with provider: {provider} (idx={idx})")
            log_event(stage="resilience", event="provider_attempt", provider=provider, attempt=idx)

            def make_runner(p: str) -> Callable[[], Coroutine[Any, Any, T]]:
                return lambda: runner(p)

            return await with_retry(make_runner(provider), policy=p_policy)
        except Exception as e:
            last_exc = e
            if idx < len(chain) - 1:
                next_provider = chain[idx + 1]
                log_event(
                    stage="resilience",
                    event="provider_failed_switching",
                    old_provider=provider,
                    next_provider=next_provider,
                    error=str(e),
                )
                logger.warning(
                    f"Provider {provider} failed after retries. "
                    f"Falling back to {next_provider}. Error: {e}"
                )
                await on_fallback(provider, next_provider, e)
            else:
                log_event(
                    stage="resilience", event="all_providers_failed", level="error", error=str(e)
                )
                logger.error(f"All providers in chain {chain} failed.")

    if last_exc:
        raise last_exc
    raise RuntimeError("Fallback chain exited without result or exception")
