"""L0 活状态路由(C5 接线)—— 把 obase.ProviderLiveState 接进 provider 路由/fallback。

`ProviderContract`/静态定价回答"多少钱";这里回答"现在还能不能用":某 provider 是否欠费/
不健康。信号来自**滚动 403 率**(provider 调用失败即累积;fal/DashScope 欠费表现为 403/
"exhausted balance")→ 拉低 health → 路由门 `provider_routable` 跳过它。余额 API(若有)经
`refresh_fal_balance` 补 balance_usd。告警归 Aegis(消费同一 ProviderLiveState)。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from obase.provider_live_state import ProviderLiveState, Rolling403Rate, fal_balance_probe

logger = logging.getLogger(__name__)

# fal 计费 provider —— 共享同一 fal 余额/403 信号。
_FAL_PROVIDERS = frozenset({"ltx2_cloud", "veo3", "kling_v2", "hailuo"})
_WINDOW = 20
_MAX_403_RATE = 0.5  # 滚动窗口 403 率 > 此 → 视为不可路由(health < 1-0.5)。

_LIVE = ProviderLiveState()
_RATES: dict[str, Rolling403Rate] = {}


def get_live_state() -> ProviderLiveState:
    """进程内活状态单例(供路由/熔断读;Aegis 亦可消费)。"""
    return _LIVE


def _reset_for_tests() -> None:
    """清空活状态(仅测试用,保证隔离)。"""
    global _LIVE
    _LIVE = ProviderLiveState()
    _RATES.clear()


def record_provider_outcome(name: str, *, is_403: bool) -> None:
    """记一次 provider 调用结果(是否 403/欠费),更新滚动率 → 活状态 health。"""
    rate = _RATES.setdefault(name, Rolling403Rate(window=_WINDOW))
    rate.record(is_403=is_403)
    _LIVE.update(name, health=rate.health())


def provider_routable(name: str) -> bool:
    """活状态路由门:滚动 403 率未超阈(health 足够)才可路由。

    无记录 → True(未探到不误杀,退回原行为)。
    """
    return _LIVE.healthy(name, min_health=1.0 - _MAX_403_RATE)


async def refresh_fal_balance(*, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """探 fal 余额 → 更新 fal 系 provider 的 balance_usd。best-effort;无端点则 source=unknown。"""
    cfg: dict[str, Any] = dict(config or {})
    cfg.setdefault("FAL_API_KEY", os.getenv("FAL_API_KEY", ""))
    if os.getenv("FAL_BALANCE_URL"):
        cfg.setdefault("FAL_BALANCE_URL", os.environ["FAL_BALANCE_URL"])
    try:
        probe = await fal_balance_probe(config=cfg)
    except Exception as e:  # pragma: no cover - best-effort
        logger.warning("fal balance probe failed: %s", e)
        return {"balance_usd": None, "ok": True, "source": "error"}
    bal = probe.get("balance_usd")
    if bal is not None:
        for p in _FAL_PROVIDERS:
            _LIVE.update(p, balance_usd=bal)
    return probe
