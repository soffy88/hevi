"""SPEC-003 ①立意 —— 素材 + 用户意图 → Concept 草稿。人审核锁定后才放行②剧本。

G1 阶段"够用即可"(生成质量专项是 SPEC-003 §6 阶段2),复用 hevi/director/intent.py 已验证的
"LLM 解析失败 → 兜底默认值,绝不阻断"既定惯例。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hevi.director.pipeline_schemas import Concept

logger = logging.getLogger(__name__)

_ARCHETYPES = frozenset({"short", "1-5min", "5-15min", "15-45min", "45min+"})

_CONCEPT_PROMPT = """根据下面的素材,提炼视频立意,只输出 JSON:
{{"theme": "主题(一句话)", "tone": "基调(如 悬疑压抑/温情治愈)",
"style": "风格倾向(如 电影感/国风水墨)", "target_audience": "目标观众",
"duration_archetype": "short|1-5min|5-15min|15-45min|45min+",
"quality_bar": "品质基准(如 标清快速出片/精品慢工)"}}

用户意图提示:{intent_hint}

素材:
{material_text}"""


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=1024)
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _resolve_llm(llm: Any) -> Any:
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    # 结构化 JSON 输出优先用 qwen_cloud(本地 ollama 对这类任务不可靠,
    # 同 e2e-local-llm-json-blocker 记录的既有教训)。
    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


async def generate_concept_draft(
    *, material_text: str, intent_hint: str = "", llm: Any = None
) -> Concept:
    """素材(+可选用户意图提示)→ Concept 草稿。LLM 失败/解析失败 → 兜底默认值,不阻断
    (人审核阶段本来就会改,草稿不必完美)。"""
    resolved_llm = _resolve_llm(llm)
    prompt = _CONCEPT_PROMPT.format(intent_hint=intent_hint or "无", material_text=material_text)
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("concept draft LLM failed, using defaults: %s", e)
        data = {}

    arch = data.get("duration_archetype")
    return Concept(
        theme=str(data.get("theme") or "").strip(),
        tone=str(data.get("tone") or "").strip(),
        style=str(data.get("style") or "").strip(),
        target_audience=str(data.get("target_audience") or "").strip(),
        duration_archetype=arch if arch in _ARCHETYPES else "1-5min",
        quality_bar=str(data.get("quality_bar") or "").strip(),
    )
