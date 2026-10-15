"""短剧规划层 LLM 通道 —— 显式 `llm_channel` 配置，默认免费通道。

规划层（storygraph 章节事件图、season_planner 分集、三层审稿）全部走这里拿 LLM，绝不
落到付费 DashScope（`qwen_cloud`）。通道实现见 `hevi/providers/free_llm.py`。

优先级由 `settings.dramaplan_llm_channel` 控制（默认 ``auto``）：
  ``auto`` 依次尝试 omniroute_free → nim → opencode → teamo_free → ollama → default。

规划层必须能在**没有任何 LLM** 时用确定性规则兜底（见各模块的规则回退分支）；本模块
只负责解析通道，不负责兜底决策。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_planning_llm(channel: str | None = None) -> tuple[str, Any]:
    """解析短剧规划用的免费文本 LLM。

    Args:
        channel: 显式通道名；``None`` 时读 `settings.dramaplan_llm_channel`（默认 auto）。

    Returns:
        ``(channel_name, caller)``。

    Raises:
        RuntimeError: 没有任何免费通道可用（调用方应走确定性规则兜底）。
    """
    if channel is None:
        try:
            from hevi.core.config import settings

            channel = settings.dramaplan_llm_channel
        except Exception:
            channel = "auto"
    from hevi.providers.free_llm import resolve_free_llm

    name, caller = resolve_free_llm(channel)
    logger.info("dramaplan 规划 LLM 通道: %s", name)
    return name, caller


__all__ = ["resolve_planning_llm"]
