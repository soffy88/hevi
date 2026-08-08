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
    image_pool_size: int = 1,
) -> list[str]:
    """topic → num_shots 条分镜画面描述(视觉 prompt)。

    image_pool_size > 1 时启用图像池选择:每镜先生成 pool_size 个候选画面,
    再按确定性启发(与主题相关性 + 描述长度)选最优,去重后返回——
    对标 DramaClaw 分镜的图像池选择。"""
    if image_pool_size < 1:
        raise ValueError("image_pool_size must be >= 1")
    if num_shots < 1:
        raise ValueError("num_shots must be >= 1")
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    if image_pool_size > 1:
        return await _plan_with_pool(
            topic=topic, num_shots=num_shots, style=style, llm=llm,
            pool_size=image_pool_size,
        )

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


# ── 图像池选择(对标 DramaClaw):每镜多候选 → 确定性启发选最优 ──────────
def _pool_score(candidate: str, topic: str) -> float:
    """候选画面评分:主题相关词命中(权重高) + 描述充实度(长度适中)。"""
    score = 0.0
    for word in topic:
        if word.strip() and word.strip() in candidate:
            score += 3.0
    # 描述充实度: 20~60 字最佳,过长(冗余)/过短(空洞)降分
    length = len(candidate)
    if 20 <= length <= 60:
        score += 2.0
    elif length > 60:
        score += 1.0
    return score


def select_best_from_pool(candidates: list[str], topic: str) -> str:
    """候选池选最优: 去重(按首 12 字) + 评分排序。"""
    seen: set[str] = set()
    unique: list[str] = []
    for cand in candidates:
        key = cand[:12]
        if key not in seen:
            seen.add(key)
            unique.append(cand)
    if not unique:
        return ""
    return max(unique, key=lambda c: _pool_score(c, topic))


async def _plan_with_pool(
    *,
    topic: str,
    num_shots: int,
    style: str,
    llm: Any,
    pool_size: int,
) -> list[str]:
    """每镜生成 pool_size 个候选画面 → 池选择 → num_shots 条最优。"""
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")
    total = num_shots * pool_size
    prompt = (
        f"为主题《{topic}》(风格:{style})写 {total} 个分镜画面候选(每镜 {pool_size} 个变体)。"
        f'只输出 JSON 数组,每条一句具体的视觉描述,尽量互不相同。'
    )
    try:
        resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
        data = _safe_json_list(resp.get("content") if hasattr(resp, "get") else str(resp))
        candidates = [str(s).strip() for s in data if str(s).strip()]
    except Exception as e:
        logger.warning("storyboard pool LLM failed, using placeholders: %s", e)
        candidates = []

    # 按 pool_size 分组,每组池选择 1 条;不足组数时用兜底
    shots: list[str] = []
    for i in range(num_shots):
        group = candidates[i * pool_size:(i + 1) * pool_size]
        if group:
            shots.append(select_best_from_pool(group, topic))
        else:
            shots.append(f"{topic} — 镜头 {i + 1}")
    return shots
