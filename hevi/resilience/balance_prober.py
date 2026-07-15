"""余额探针调度(HEVI 路线图 Phase1 #30)。

`refresh_fal_balance`(hevi/resilience/live_state.py)之前只是定义了但从未被任何地方
调用过——写了却没接上调度,balance_usd 永远是空的,`provider_routable`/`selector.py`
早就支持读它(`ProviderLiveState.healthy(min_balance_usd=...)`),只是没有活数据。这里
补的是调度这一层,不改路由/健康判定逻辑。

镜像 `hevi.queue.worker.QueueWorker` 的 run/stop 循环形状,同一套生命周期管理惯例。
"""

from __future__ import annotations

import asyncio
import logging

from hevi.resilience.live_state import refresh_fal_balance

logger = logging.getLogger(__name__)


class BalanceProber:
    def __init__(self, *, poll_interval: float = 3600.0):
        self.poll_interval = poll_interval
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("Balance prober started (interval=%.0fs)", self.poll_interval)
        while self._running:
            try:
                probe = await refresh_fal_balance()
                logger.info("balance probe: %s", probe)
            except Exception as e:  # best-effort: 探针失败不该拖垮进程
                logger.warning("balance probe failed: %s", e)
            await asyncio.sleep(self.poll_interval)
        logger.info("Balance prober stopped")

    def stop(self) -> None:
        logger.info("Stopping balance prober...")
        self._running = False
