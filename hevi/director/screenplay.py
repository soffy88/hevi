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

_SCREENPLAY_PROMPT = """把下面的素材改写成白话分场剧本。

**白话要求(为了配音自然、观众听得懂):** 文言字词转成现代口语,不要"之乎者也""尔/汝/
寡人"这类文言腔,也不要硬拗成半文半白。

**但更重要——贴近原文,不要削弱:**
- **忠实原文的完整意思和情感力度,不许大幅删减、不许压缩成一两句。** 原文说了三层意思,
  白话也要说三层;原文是一段慷慨陈词,白话也要是一段慷慨陈词,不能缩成一句反问。
- **保留原文的关键比喻、名句、意象**(如"兄弟如手足,妻子如衣服;衣服破了还能补,手足
  断了怎么接得回来")——用白话说出来,但不能丢掉这个比喻本身。
- **保留人物的语气分量**:该恳切的恳切、该痛切的痛切、该有气势的有气势。原文的排比、
  递进、反问,白话里对应保留。
- 一句话:**你是在"翻译+口语化",不是在"缩写+改编"。** 宁可长一点忠实,不要短而失神。

立意约束:主题「{theme}」,基调「{tone}」,风格「{style}」。

分场时把每场的文字拆成两块:
- narration:非对白的叙述文字(白话,忠实原文情节,不删减关键动作/转折)
- dialogue:人物开口说的话,每句标出是谁说的(白话口语,但保留原文的完整意思与力度);
  再标出这句是**对谁说的**(target_name,须是本场在场人物;独白/对众留空)

只输出 JSON:
{{"scenes": [
  {{"scene_no": 1, "time": "时间", "location": "地点",
    "characters_present": ["人物名", ...],
    "narration": "该场叙述(白话)",
    "dialogue": [{{
      "character_name": "人物名", "text": "白话台词", "target_name": "受话人物名或留空"}}],
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
                target_name=str(d.get("target_name") or "").strip(),
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
