"""余额探针调度测试(HEVI 路线图 Phase1 #30)。

refresh_fal_balance 本身早就存在(hevi/resilience/live_state.py),但从未被任何地方
调用过——这里测的是新加的调度层(BalanceProber),不是探针本身的逻辑。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from hevi.resilience.balance_prober import BalanceProber


@pytest.mark.asyncio
async def test_prober_calls_refresh_fal_balance_periodically():
    prober = BalanceProber(poll_interval=0.01)
    with patch(
        "hevi.resilience.balance_prober.refresh_fal_balance", new_callable=AsyncMock
    ) as mock_refresh:
        mock_refresh.return_value = {"balance_usd": 10.0, "ok": True, "source": "api"}
        task = asyncio.create_task(prober.run())
        await asyncio.sleep(0.05)
        prober.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert mock_refresh.call_count >= 2  # 至少跑了几轮,不是只跑一次就退出


@pytest.mark.asyncio
async def test_prober_survives_probe_failure():
    """探针失败不该拖垮整个循环——下一轮还得接着跑。"""
    prober = BalanceProber(poll_interval=0.01)
    with patch(
        "hevi.resilience.balance_prober.refresh_fal_balance",
        new_callable=AsyncMock,
        side_effect=RuntimeError("probe exploded"),
    ) as mock_refresh:
        task = asyncio.create_task(prober.run())
        await asyncio.sleep(0.05)
        prober.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert mock_refresh.call_count >= 2


@pytest.mark.asyncio
async def test_prober_stop_halts_the_loop():
    prober = BalanceProber(poll_interval=0.01)
    with patch(
        "hevi.resilience.balance_prober.refresh_fal_balance", new_callable=AsyncMock
    ) as mock_refresh:
        task = asyncio.create_task(prober.run())
        await asyncio.sleep(0.03)
        prober.stop()
        await asyncio.sleep(0.03)
        count_after_stop = mock_refresh.call_count
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    # stop() 之后不应该再新增调用(允许一次正在飞行中的调用完成)
    assert mock_refresh.call_count <= count_after_stop + 1
