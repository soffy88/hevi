"""SPEC-003 ③设计清单 —— 锁定 Screenplay → DesignList 草稿(场景/人物/道具三张清单)。

这是主线"人物/场景乱跳"崩坏症状的直接根治点:扫描剧本自动分解出三张待锁定清单,人审核后
锁定(见 hevi/api/routers/director_pipeline.py 的 design-list/lock 端点,锁定时才真正落成
Subject 资产)。**这里只产出草稿,不建 Subject——建 Subject 是锁定动作,不是草稿生成动作。**
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.pipeline_schemas import (
    DesignCharacter,
    DesignList,
    DesignProp,
    DesignScene,
    Screenplay,
)

logger = logging.getLogger(__name__)

_DESIGN_LIST_PROMPT = """扫描下面的分场剧本,分解出三张清单:出场人物、场景、关键反复出现的
道具。**只收录剧本里真实提到的,不要凭空发明。**

只输出 JSON:
{{"characters": [{{"name": "人物名(须跟剧本里的名字一致)", "appearance": "外貌",
   "wardrobe": "衣着", "hairstyle": "发型", "personality": "性格",
   "is_lead": true或false, "voice_hint": "声线倾向(如 低沉沙哑/清亮少年音)"}}],
 "scenes": [{{"name": "场景名(须跟剧本里的地点一致)", "environment": "环境描述",
   "lighting": "光照", "mood": "氛围", "is_primary": true或false}}],
 "props": [{{"name": "道具名", "appearance": "外观"}}]}}

分场剧本:
{screenplay_text}"""


def _screenplay_to_text(screenplay: Screenplay) -> str:
    lines: list[str] = []
    for s in screenplay.scenes:
        lines.append(f"第{s.scene_no}场 {s.time} {s.location}")
        lines.append(f"出场:{'、'.join(s.characters_present)}")
        if s.narration:
            lines.append(f"叙述:{s.narration}")
        lines.extend(f"{d.character_name}:{d.text}" for d in s.dialogue)
    return "\n".join(lines)


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


async def generate_design_list_draft(*, screenplay: Screenplay, llm: Any = None) -> DesignList:
    """锁定 Screenplay → DesignList 草稿。LLM 失败/解析失败 → 从剧本里确定性地兜底提取
    人物名(characters_present 去重)+ 场景名(location 去重),外貌/环境等描述留空待人工补,
    不因草稿生成失败阻断——空描述好过整体失败。"""
    resolved_llm = _resolve_llm(llm)
    prompt = _DESIGN_LIST_PROMPT.format(screenplay_text=_screenplay_to_text(screenplay))
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("design list draft LLM failed, using fallback: %s", e)
        data = {}

    characters = [
        DesignCharacter(
            name=str(c.get("name") or "").strip(),
            appearance=str(c.get("appearance") or "").strip(),
            wardrobe=str(c.get("wardrobe") or "").strip(),
            hairstyle=str(c.get("hairstyle") or "").strip(),
            personality=str(c.get("personality") or "").strip(),
            is_lead=bool(c.get("is_lead")),
            voice_hint=str(c.get("voice_hint") or "").strip(),
        )
        for c in (data.get("characters") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    ]
    scenes = [
        DesignScene(
            name=str(s.get("name") or "").strip(),
            environment=str(s.get("environment") or "").strip(),
            lighting=str(s.get("lighting") or "").strip(),
            mood=str(s.get("mood") or "").strip(),
            is_primary=bool(s.get("is_primary")),
        )
        for s in (data.get("scenes") or [])
        if isinstance(s, dict) and str(s.get("name") or "").strip()
    ]
    props = [
        DesignProp(
            name=str(p.get("name") or "").strip(), appearance=str(p.get("appearance") or "").strip()
        )
        for p in (data.get("props") or [])
        if isinstance(p, dict) and str(p.get("name") or "").strip()
    ]

    if not characters:
        seen: set[str] = set()
        for s in screenplay.scenes:
            for name in s.characters_present:
                if name and name not in seen:
                    seen.add(name)
                    characters.append(DesignCharacter(name=name))
    if not scenes:
        seen_loc: set[str] = set()
        for s in screenplay.scenes:
            if s.location and s.location not in seen_loc:
                seen_loc.add(s.location)
                scenes.append(DesignScene(name=s.location))

    return DesignList(characters=characters, scenes=scenes, props=props)
