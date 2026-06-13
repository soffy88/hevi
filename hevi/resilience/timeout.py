import asyncio
from collections.abc import Coroutine
from typing import Any


async def with_timeout[T](coro: Coroutine[Any, Any, T], timeout_s: float) -> T:
    """Run a coroutine with a timeout.

    Args:
        coro: The coroutine to run.
        timeout_s: The timeout in seconds.

    Returns:
        T: The result of the coroutine.

    Raises:
        TimeoutError: If the coroutine takes longer than timeout_s.
    """
    return await asyncio.wait_for(coro, timeout=timeout_s)
