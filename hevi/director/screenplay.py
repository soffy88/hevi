"""SPEC-003 ②剧本 —— 锁定 Concept + 素材原文 → Screenplay 白话分场剧本草稿。

**核心要求(治"文言不是白话"这一崩坏症状):不管素材是文言还是白话,剧本一律白话重写。**
文言原文是素材,剧本是重写产物,不是搬运——prompt 里显式要求"逐场重写成现代白话",这条红线
直接写进 prompt,不靠模型自觉。

每场结构化拆出"叙述"(narration)与"人物对白"(dialogue)两块,为④分镜级切出带 speaker
的台词行打基础(见 pipeline_schemas.py 的 ScreenplayDialogueLine)。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.pipeline_schemas import (
    Concept,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
)

logger = logging.getLogger(__name__)

_SCREENPLAY_PROMPT = """把下面的素材改写成白话分场剧本。**硬性要求:不管素材原文是文言文
还是白话,每一场的叙述与对白都必须是现代白话(口语),不要"之乎者也""尔/汝/寡人"这类文言词,
不要把白话硬拗成半文半白**——文言原文只是素材,剧本是你的重写产物。

立意约束:主题「{theme}」,基调「{tone}」,风格「{style}」。

分场时把每场的文字拆成两块:
- narration:非对白的叙述文字(白话)
- dialogue:人物开口说的话,每句标出是谁说的(白话,不是文言翻译腔)

只输出 JSON:
{{"scenes": [
  {{"scene_no": 1, "time": "时间", "location": "地点",
    "characters_present": ["人物名", ...],
    "narration": "该场叙述(白话)",
    "dialogue": [{{"character_name": "人物名", "text": "白话台词"}}],
    "event_summary": "该场事件概要"}}
]}}

素材:
{material_text}"""


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    # 见 concept.py 同名函数注释:qwen_cloud 适配器构造时同步发 HTTP 请求,不放线程池
    # 会把单线程 event loop 卡住到调用返回为止。
    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=4096)

    obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=45.0)
    resp = await obj if hasattr(obj, "__await__") else obj
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

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


async def generate_screenplay_draft(
    *, concept: Concept, material_text: str, llm: Any = None
) -> Screenplay:
    """锁定 Concept + 素材原文 → Screenplay 草稿。LLM 失败/解析失败 → 返回单场的兜底剧本
    (叙述=原文本身,人审核阶段可以手工补,不因草稿生成失败阻断流程)。"""
    resolved_llm = _resolve_llm(llm)
    prompt = _SCREENPLAY_PROMPT.format(
        theme=concept.theme or "(未定)",
        tone=concept.tone or "(未定)",
        style=concept.style or "(未定)",
        material_text=material_text,
    )
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("screenplay draft LLM failed, using fallback: %s", e)
        data = {}

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        return Screenplay(
            scenes=[ScreenplayScene(scene_no=1, narration=material_text, event_summary="")]
        )

    scenes: list[ScreenplayScene] = []
    for i, raw in enumerate(raw_scenes):
        if not isinstance(raw, dict):
            continue
        raw_dialogue = raw.get("dialogue") or []
        dialogue = [
            ScreenplayDialogueLine(
                character_name=str(d.get("character_name") or "").strip(),
                text=str(d.get("text") or "").strip(),
            )
            for d in raw_dialogue
            if isinstance(d, dict) and str(d.get("text") or "").strip()
        ]
        scenes.append(
            ScreenplayScene(
                scene_no=int(raw.get("scene_no") or i + 1),
                time=str(raw.get("time") or "").strip(),
                location=str(raw.get("location") or "").strip(),
                characters_present=[
                    str(c).strip() for c in (raw.get("characters_present") or []) if str(c).strip()
                ],
                narration=str(raw.get("narration") or "").strip(),
                dialogue=dialogue,
                event_summary=str(raw.get("event_summary") or "").strip(),
            )
        )
    return Screenplay(scenes=scenes or [ScreenplayScene(scene_no=1, narration=material_text)])
