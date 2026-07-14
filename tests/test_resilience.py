import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hevi.resilience.errors import (
    DegradableError,
    HeviError,
    RateLimitError,
    RetryableError,
    UnretryableError,
    classify_error,
)
from hevi.resilience.fallback_chain import run_with_fallback
from hevi.resilience.retry_policy import RetryPolicy, with_retry


def test_classify_error():
    # Retryable
    err_429 = httpx.HTTPStatusError("429", request=AsyncMock(), response=httpx.Response(429))
    assert isinstance(classify_error(err_429), RateLimitError)

    err_500 = httpx.HTTPStatusError("500", request=AsyncMock(), response=httpx.Response(500))
    assert isinstance(classify_error(err_500), RetryableError)

    assert isinstance(classify_error(httpx.TimeoutException("timeout")), RetryableError)

    # Unretryable
    err_401 = httpx.HTTPStatusError("401", request=AsyncMock(), response=httpx.Response(401))
    assert isinstance(classify_error(err_401), UnretryableError)
    assert isinstance(classify_error(ValueError("logic bug")), UnretryableError)


def test_classify_error_message_based():
    """P1-5:按消息识别 hevi 实际会撞的错(非 httpx 类型的 RuntimeError 等)。"""
    # 账户锁定/欠费/配额/配置缺失 → 不可重试(重试无用)
    for msg in (
        "fal submit 403: User is locked. Reason: Exhausted balance.",
        "Access denied ... account ... overdue-payment",
        "FAL_API_KEY not configured",
        "vibevoice package not installed",
        "insufficient_credits",
    ):
        assert isinstance(classify_error(RuntimeError(msg)), UnretryableError), msg

    # 瞬时网络/服务端 → 可重试
    for msg in (
        "[Errno 111] Connection refused",
        "connection reset by peer",
        "read timed out",
        "503 Service Unavailable",
    ):
        assert isinstance(classify_error(RuntimeError(msg)), RetryableError), msg


def test_degradable_error_is_hevi_error_not_retryable():
    """DegradableError 属 HeviError,但不是 Retryable/Unretryable(降级语义,不参与重试)。"""
    e = DegradableError("audio synth failed; degrade to video-only")
    assert isinstance(e, HeviError)
    assert not isinstance(e, (RetryableError, UnretryableError))


@pytest.mark.asyncio
async def test_with_retry_success_first_time():
    mock_coro = AsyncMock(return_value="success")
    res = await with_retry(lambda: mock_coro())
    assert res == "success"
    assert mock_coro.call_count == 1


@pytest.mark.asyncio
async def test_with_retry_success_second_time():
    mock_coro = AsyncMock()
    mock_coro.side_effect = [httpx.TimeoutException("fail"), "success"]

    # Mock sleep to speed up test
    with patch("asyncio.sleep", new_callable=AsyncMock):
        policy = RetryPolicy(max_attempts=3, base_delay_s=0.1)
        res = await with_retry(lambda: mock_coro(), policy=policy)
        assert res == "success"
        assert mock_coro.call_count == 2


@pytest.mark.asyncio
async def test_with_retry_exhausted():
    mock_coro = AsyncMock(side_effect=httpx.TimeoutException("fail"))
    with patch("asyncio.sleep", new_callable=AsyncMock), pytest.raises(httpx.TimeoutException):
        await with_retry(lambda: mock_coro(), policy=RetryPolicy(max_attempts=2))
    assert mock_coro.call_count == 2


@pytest.mark.asyncio
async def test_with_retry_unretryable():
    mock_coro = AsyncMock(side_effect=ValueError("bad param"))
    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ValueError, match="bad param"):
            await with_retry(lambda: mock_coro())
    assert mock_coro.call_count == 1


@pytest.mark.asyncio
async def test_run_with_fallback_success():
    runner = AsyncMock(return_value="done")
    on_fallback = AsyncMock()

    res = await run_with_fallback(
        initial_provider="ltx2_cloud", runner=runner, on_fallback=on_fallback
    )
    assert res == "done"
    runner.assert_called_once_with("ltx2_cloud")
    on_fallback.assert_not_called()


@pytest.mark.asyncio
async def test_run_with_fallback_switching():
    # First provider fails, second succeeds
    def runner_side_effect(p: str):
        if p == "ltx2_cloud":
            raise httpx.TimeoutException("ltx2 down")
        return f"done_{p}"

    runner = AsyncMock(side_effect=runner_side_effect)
    on_fallback = AsyncMock()

    with (
        patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "hevi.resilience.fallback_chain.provider_health_check",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        res = await run_with_fallback(
            initial_provider="ltx2_cloud",
            runner=runner,
            on_fallback=on_fallback,
            retry_policy=RetryPolicy(max_attempts=1),  # No retries to speed up fallback
        )

    # ltx2_cloud 的降级目标现在是 happyhorse_1_1_maas_lock(fal 欠费后唯一有余额的通道,
    # 见 fallback_chain.py 的 _TERMINAL)。
    assert res == "done_happyhorse_1_1_maas_lock"
    assert runner.call_count == 2
    on_fallback.assert_called_once()


@pytest.mark.asyncio
async def test_run_with_fallback_all_failed():
    runner = AsyncMock(side_effect=httpx.TimeoutException("all down"))
    on_fallback = AsyncMock()

    with (
        patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock),
        patch(
            "hevi.resilience.fallback_chain.provider_health_check",
            new_callable=AsyncMock,
            return_value=True,
        ),
        pytest.raises(httpx.TimeoutException),
    ):
        await run_with_fallback(
            initial_provider="ltx2_cloud",
            runner=runner,
            on_fallback=on_fallback,
            retry_policy=RetryPolicy(max_attempts=1),
        )
    assert runner.call_count == 2  # ltx2 and wan


@pytest.mark.asyncio
async def test_with_timeout_triggered():
    from hevi.resilience.timeout import with_timeout

    async def slow_coro():
        await asyncio.sleep(0.5)
        return "done"

    with pytest.raises(asyncio.TimeoutError):
        await with_timeout(slow_coro(), timeout_s=0.1)


@pytest.mark.asyncio
async def test_with_timeout_success():
    from hevi.resilience.timeout import with_timeout

    async def fast_coro():
        return "fast"

    res = await with_timeout(fast_coro(), timeout_s=1.0)
    assert res == "fast"


@pytest.mark.asyncio
async def test_coro_factory_recreation_verification():
    """Verify that coro_factory is called multiple times on retry."""
    factory_calls = 0

    async def my_coro():
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls < 2:
            raise httpx.TimeoutException("fail")
        return "ok"

    with patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock):
        res = await with_retry(lambda: my_coro(), policy=RetryPolicy(max_attempts=3))
        assert res == "ok"
        assert factory_calls == 2


@pytest.mark.asyncio
async def test_retry_jitter_logic():
    """Test that jitter doesn't crash and adds variance."""
    side_effects = [httpx.TimeoutException("f1"), httpx.TimeoutException("f2"), "ok"]
    mock_coro = AsyncMock(side_effect=side_effects)

    with patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        policy = RetryPolicy(max_attempts=3, jitter=True)
        await with_retry(lambda: mock_coro(), policy=policy)
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0].args[0] > 0


def test_classify_error_detailed():
    # 404
    err_404 = httpx.HTTPStatusError("Not Found", request=AsyncMock(), response=httpx.Response(404))
    assert isinstance(classify_error(err_404), UnretryableError)

    # 503
    err_503 = httpx.HTTPStatusError(
        "Service Unavailable", request=AsyncMock(), response=httpx.Response(503)
    )
    assert isinstance(classify_error(err_503), RetryableError)

    # Generic exception
    assert isinstance(classify_error(RuntimeError("boom")), UnretryableError)


@pytest.mark.asyncio
async def test_run_with_fallback_empty_chain():
    runner = AsyncMock(return_value="ok")
    on_fallback = AsyncMock()
    res = await run_with_fallback(
        initial_provider="unknown", runner=runner, on_fallback=on_fallback
    )
    assert res == "ok"
    runner.assert_called_once_with("unknown")


@pytest.mark.asyncio
async def test_run_with_fallback_final_failure_exception():
    runner = AsyncMock(side_effect=ValueError("critical"))
    on_fallback = AsyncMock()
    with pytest.raises(ValueError, match="critical"):
        await run_with_fallback(
            initial_provider="ltx2_cloud",
            runner=runner,
            on_fallback=on_fallback,
            retry_policy=RetryPolicy(max_attempts=1),
        )


@pytest.mark.asyncio
async def test_task_service_run_task_with_fallback_integration():
    from hevi.tasks.task_service import TaskService

    repo = AsyncMock()
    task_id = uuid.uuid4()
    repo.get_task.return_value = {
        "id": task_id,
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "ltx2_cloud",
        "audio_provider": "vibevoice",
        "config_json": {},
    }

    service = TaskService(repo)

    with (
        patch("hevi.tasks.task_service.orchestrate_longvideo") as mock_orch,
        patch(
            "hevi.resilience.fallback_chain.provider_health_check",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("hevi.resilience.retry_policy.asyncio.sleep", new_callable=AsyncMock),
    ):

        def orch_side_effect(**kwargs: Any):
            if kwargs["video_provider"] == "ltx2_cloud":
                raise httpx.TimeoutException("ltx2 fail")
            return {"url": "video.mp4", "duration": 180.0, "metadata": {"shots": 5}}

        mock_orch.side_effect = orch_side_effect

        res = await service.run_task(task_id)

    assert res["status"] == "completed"
    assert repo.update_task.call_count >= 3
    # Check fallback call —— ltx2_cloud 降级到 happyhorse_1_1_maas_lock(见 _TERMINAL)。
    fallback_call = [
        c
        for c in repo.update_task.call_args_list
        if c.args[1].get("video_provider") == "happyhorse_1_1_maas_lock"
    ]
    assert len(fallback_call) == 1


@pytest.mark.asyncio
async def test_live_state_gates_unroutable_provider():
    """L0 活状态:滚动 403 率把 provider 标为不可路由 → run_with_fallback 不 attempt 它。"""
    from hevi.resilience import live_state

    live_state._reset_for_tests()
    try:
        # 门测:无记录→可路由;灌满 403→不可路由。用 ltx2_cloud 的降级目标
        # happyhorse_1_1_maas_lock 做被门掉的那一个(链 [ltx2_cloud, happyhorse_1_1_maas_lock])。
        gated = "happyhorse_1_1_maas_lock"
        assert live_state.provider_routable(gated) is True
        for _ in range(live_state._WINDOW):
            live_state.record_provider_outcome(gated, is_403=True)
        assert live_state.provider_routable(gated) is False

        attempted: list[str] = []

        async def runner(p: str) -> str:
            attempted.append(p)
            raise RuntimeError("fal submit 403: User is locked (exhausted balance)")

        async def on_fallback(old: str, new: str, exc: Exception) -> None:
            pass

        with patch(
            "hevi.resilience.fallback_chain.provider_health_check",
            new_callable=AsyncMock,
            return_value=True,
        ):
            with pytest.raises(Exception):
                # 链 [ltx2_cloud, happyhorse_1_1_maas_lock]
                await run_with_fallback(
                    initial_provider="ltx2_cloud",
                    runner=runner,
                    on_fallback=on_fallback,
                )
        # ltx2_cloud 可路由被 attempt(失败);降级目标不可路由 → 从未 attempt
        assert attempted == ["ltx2_cloud"]
        assert gated not in attempted
    finally:
        live_state._reset_for_tests()  # 防污染后续测试(全局单例)


def test_is_balance_403_detection():
    from hevi.resilience.fallback_chain import _is_balance_403

    assert _is_balance_403(RuntimeError("fal 403: User is locked")) is True
    assert _is_balance_403(RuntimeError("exhausted balance")) is True
    assert _is_balance_403(RuntimeError("connection reset")) is False
