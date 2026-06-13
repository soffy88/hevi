import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.monitoring.metrics import (
    provider_api_calls_total,
    video_generation_in_progress,
    video_generation_total,
)
from hevi.observability import (
    get_trace_id,
    log_event,
    set_trace_id,
    track_provider_call,
    track_video_generation,
)


@pytest.mark.asyncio
async def test_track_provider_call_success():
    provider = "test_p"
    before = provider_api_calls_total.labels(provider=provider, status="success")._value.get()
    async with track_provider_call(provider):
        pass
    after = provider_api_calls_total.labels(provider=provider, status="success")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_track_provider_call_error():
    provider = "test_err"
    before = provider_api_calls_total.labels(provider=provider, status="error")._value.get()
    with pytest.raises(ValueError):
        async with track_provider_call(provider):
            raise ValueError("fail")
    after = provider_api_calls_total.labels(provider=provider, status="error")._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_track_video_generation_labels():
    provider = "ltx2"
    archetype = "1-5min"
    before = video_generation_total.labels(
        provider=provider, duration_archetype=archetype, status="success"
    )._value.get()
    async with track_video_generation(provider, archetype):
        pass
    after = video_generation_total.labels(
        provider=provider, duration_archetype=archetype, status="success"
    )._value.get()
    assert after == before + 1


@pytest.mark.asyncio
async def test_video_generation_in_progress():
    initial = video_generation_in_progress._value.get()
    async with track_video_generation("p", "a"):
        assert video_generation_in_progress._value.get() == initial + 1
    assert video_generation_in_progress._value.get() == initial


def test_trace_id_context():
    tid = uuid.uuid4()
    set_trace_id(tid)
    assert get_trace_id() == str(tid)


def test_structured_log_format(caplog):
    caplog.set_level("INFO", logger="hevi.structured")
    tid = str(uuid.uuid4())
    set_trace_id(tid)
    log_event(stage="test", event="hello", key="val")
    assert len(caplog.records) == 1
    data = json.loads(caplog.records[0].message)
    assert data["trace_id"] == tid
    assert data["stage"] == "test"
    assert data["event"] == "hello"
    assert data["key"] == "val"


@pytest.mark.asyncio
async def test_fallback_chain_instrumentation():
    """Verify that fallback_chain logs events."""
    from hevi.resilience import run_with_fallback

    runner = AsyncMock(side_effect=[ValueError("f1"), "done"])
    on_fallback = AsyncMock()

    with patch("hevi.resilience.fallback_chain.log_event") as mock_log, patch(
        "hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock
    ):
        await run_with_fallback(
            initial_provider="ltx2_cloud", runner=runner, on_fallback=on_fallback
        )
        assert mock_log.call_count >= 2
        calls = [c.kwargs["event"] for c in mock_log.call_args_list]
        assert "provider_attempt" in calls
        assert "provider_failed_switching" in calls


@pytest.mark.asyncio
async def test_credits_metric_recording():
    """Verify that HeviCostTracker records credits metric."""
    from hevi.cost import HeviCostTracker
    from hevi.monitoring.metrics import credits_consumed_total

    before = credits_consumed_total.labels(user_tier="free")._value.get()
    tracker = HeviCostTracker()
    with patch.object(tracker.internal, "record", return_value=4.0):
        tracker.record_video("ltx2_cloud", 100.0)
    after = credits_consumed_total.labels(user_tier="free")._value.get()
    assert after == before + 400


@pytest.mark.asyncio
async def test_task_service_trace_id_injection():
    """Verify task_service.run_task injects trace_id."""
    from hevi.tasks.task_service import TaskService

    repo = AsyncMock()
    tid = uuid.uuid4()
    repo.get_task.return_value = {
        "id": tid,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "vibevoice",
        "config_json": {},
    }
    service = TaskService(repo)

    with patch("hevi.tasks.task_service.set_trace_id") as mock_set, patch(
        "hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock
    ) as mock_orch:
        mock_orch.return_value = {"url": "v", "duration": 10, "metadata": {"shots": 1}}
        await service.run_task(tid)
        mock_set.assert_called_with(tid)


def test_structured_log_error(caplog):
    caplog.set_level("ERROR", logger="hevi.structured")
    log_event(stage="s", event="e", level="error")
    assert caplog.records[0].levelname == "ERROR"


def test_structured_log_warning(caplog):
    caplog.set_level("WARNING", logger="hevi.structured")
    log_event(stage="s", event="e", level="warning")
    assert caplog.records[0].levelname == "WARNING"


@pytest.mark.asyncio
async def test_instrumentation_exception_propagation():
    """Verify track_provider_call propagates exception but logs error status."""
    from hevi.monitoring.metrics import provider_api_calls_total

    p = "test_prop"
    with pytest.raises(RuntimeError):
        async with track_provider_call(p):
            raise RuntimeError("prop")
    val = provider_api_calls_total.labels(provider=p, status="error")._value.get()
    assert val > 0


@pytest.mark.asyncio
async def test_instrumentation_generation_exception_propagation():
    """Verify track_video_generation propagates exception."""
    with pytest.raises(RuntimeError):
        async with track_video_generation("p", "a"):
            raise RuntimeError("prop")
    val = video_generation_total.labels(
        provider="p", duration_archetype="a", status="error"
    )._value.get()
    assert val > 0


@pytest.mark.asyncio
async def test_trace_id_propagation_orchestrator():
    """Verify that orchestrator propagates trace_id set by task_service."""
    from hevi.pipeline import orchestrate_longvideo

    tid = uuid.uuid4()
    set_trace_id(tid)
    with patch(
        "hevi.pipeline.longvideo_orchestrator.agentic_longvideo_pipeline", new_callable=AsyncMock
    ) as mock_pipe:
        mock_pipe.return_value = MagicMock(
            video_path=MagicMock(stem="test"),
            duration_s=10,
            chapters=1,
            shots_generated=1,
            provider_used={},
        )
        await orchestrate_longvideo(
            topic="test",
            duration_archetype="1-5min",
            video_provider="ltx2_cloud",
            audio_provider="vibevoice",
        )
        assert get_trace_id() == str(tid)
