"""L4 NL 意图解析 —— 自然语言需求 → Producer intent 字段。北极星"输入剧情"的输入端。

用已注册的 LLM(本地 qwen / dashscope)把一句话需求解析成结构化 intent,喂 `produce()`。
LLM 失败/输出不可解析 → 兜底(topic=原文,默认档位),绝不因解析失败阻断。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_ARCHETYPES = frozenset({"short", "1-5min", "5-15min", "15-45min", "45min+"})


def _safe_json(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


async def parse_intent(text: str, *, llm: Any = None) -> dict[str, Any]:
    """自然语言需求 → intent dict(topic/duration_archetype/num_characters/style/[budget_usd])。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = (
        "把下面的视频制作需求解析为 JSON,只输出 JSON,字段:\n"
        '{"topic": <主题字符串>, "duration_archetype": '
        '<"short"|"1-5min"|"5-15min"|"15-45min"|"45min+">, '
        '"num_characters": <整数>, "style": <风格字符串>, "budget_usd": <数字或 null>}\n'
        f"需求:{text}"
    )
    parsed: dict[str, Any] = {}
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=256)
        parsed = _safe_json(resp.get("content") if hasattr(resp, "get") else str(resp))
    except Exception as e:
        logger.warning("intent parse LLM failed, using defaults: %s", e)

    arch = parsed.get("duration_archetype")
    intent: dict[str, Any] = {
        "topic": (parsed.get("topic") or text).strip(),
        "duration_archetype": arch if arch in _ARCHETYPES else "1-5min",
        "num_characters": int(parsed.get("num_characters") or 1),
        "style": (parsed.get("style") or "cinematic"),
    }
    if parsed.get("budget_usd") is not None:
        try:
            intent["budget_usd"] = float(parsed["budget_usd"])
        except TypeError, ValueError:
            pass
    return intent
