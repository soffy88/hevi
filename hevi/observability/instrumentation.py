import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from hevi.monitoring.metrics import (
    provider_api_calls_total,
    provider_api_latency_seconds,
    video_generation_duration_seconds,
    video_generation_in_progress,
    video_generation_total,
)


@asynccontextmanager
async def track_provider_call(provider: str) -> AsyncGenerator[None]:
    """Metrics instrumentation for a provider API call."""
    start = time.monotonic()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        provider_api_calls_total.labels(provider=provider, status=status).inc()
        provider_api_latency_seconds.labels(provider=provider).observe(time.monotonic() - start)


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
