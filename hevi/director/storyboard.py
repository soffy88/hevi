"""L4 storyboard 自动分镜 —— topic → N 条分镜 prompt(喂 Director.build_canvas_graph)。

用已注册 LLM 把主题拆成 N 个镜头的画面描述。失败 → 兜底占位分镜,不阻断。
(管线内部另有自己的 storyboard;这里是给 Director 产**可编辑分镜图**用的独立轻量分镜。)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _safe_json_list(content: str | None) -> list[Any]:
    """从 LLM 输出抽分镜列表。兼容两种形态:JSON 数组,或对象(键如"镜头1画面")→ 取其值。
    小模型(llama3.2/qwen2.5)常返回对象而非数组,故都接。"""
    if not content:
        return []
    m = re.search(r"\[.*\]", content, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return list(data.values())
        except json.JSONDecodeError:
            pass
    return []


async def plan_shots(
    *,
    topic: str,
    num_shots: int = 4,
    style: str = "cinematic",
    llm: Any = None,
) -> list[str]:
    """topic → num_shots 条分镜画面描述(视觉 prompt)。"""
    if num_shots < 1:
        raise ValueError("num_shots must be >= 1")
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    prompt = (
        f"为主题《{topic}》(风格:{style})写 {num_shots} 个分镜的画面描述。"
        f'只输出 JSON 数组 ["镜头1画面","镜头2画面",...],每条一句具体的视觉描述。'
    )
    shots: list[str] = []
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=512)
        data = _safe_json_list(resp.get("content") if hasattr(resp, "get") else str(resp))
        shots = [str(s).strip() for s in data if str(s).strip()][:num_shots]
    except Exception as e:
        logger.warning("storyboard LLM failed, using placeholders: %s", e)

    if not shots:
        shots = [f"{topic} — 镜头 {i + 1}" for i in range(num_shots)]  # 兜底
    return shots
