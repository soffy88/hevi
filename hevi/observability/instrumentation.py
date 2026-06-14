import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from obase.observability import track_provider_call as obase_track_provider_call

from hevi.monitoring.metrics import (
    video_generation_duration_seconds,
    video_generation_in_progress,
    video_generation_total,
)


@asynccontextmanager
async def track_provider_call(provider: str) -> AsyncGenerator[None]:
    """Metrics instrumentation for a provider API call (delegates to obase)."""
    async with obase_track_provider_call(provider=provider, operation="generate"):
        yield


@asynccontextmanager
async def track_video_generation(
    provider: str, duration_archetype: str
) -> AsyncGenerator[None]:
    """Metrics instrumentation for a video generation job."""
    video_generation_in_progress.inc()
    start = time.monotonic()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        video_generation_in_progress.dec()
        video_generation_total.labels(
            provider=provider, duration_archetype=duration_archetype, status=status
        ).inc()
        video_generation_duration_seconds.labels(
            provider=provider, duration_archetype=duration_archetype
        ).observe(time.monotonic() - start)
