import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from obase.observability import track_provider_call as obase_track_provider_call

from hevi.monitoring.metrics import (
    provider_latency_seconds,
    provider_outcomes_total,
    video_generation_duration_seconds,
    video_generation_in_progress,
    video_generation_total,
)
from hevi.observability.trace import bind_trace_context


@asynccontextmanager
async def track_provider_call(provider: str) -> AsyncGenerator[None]:
    """Track a provider call in obase, Prometheus, and the trace context."""
    call_id = uuid4().hex
    started = time.monotonic()
    status = "success"
    async with obase_track_provider_call(provider=provider, operation="generate"):
        try:
            with bind_trace_context(provider_call_id=call_id):
                yield
        except Exception:
            status = "error"
            raise
        finally:
            provider_outcomes_total.labels(
                provider=provider, task_class="generate", status=status
            ).inc()
            provider_latency_seconds.labels(provider=provider, task_class="generate").observe(
                time.monotonic() - started
            )


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
