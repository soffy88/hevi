"""SPEC-003 ④分镜头剧本 —— 锁定 Screenplay + DesignList → ShotList 草稿。

这是主线"只有旁白没对白"崩坏症状的直接根治点:把每一场切成镜头序列,**台词行必须显式标注
speaker(哪个角色说)**,而不是把整场叙述文字囫囵吞枣丢给配音。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.pipeline_schemas import (
    DesignList,
    Screenplay,
    ShotBlocking,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)

logger = logging.getLogger(__name__)

_SHOT_LIST_PROMPT = """把下面这一场剧本切成镜头序列(通常 2-5 镜)。**台词行是重中之重:
这一场剧本里的每一句人物对白,必须原样落到某个镜头的 dialogue_lines 里,并标出是谁说的
(character_name);场景描述/过渡性文字才归入没有 character_name 的旁白行。不要把对白揉进
旁白里一笔带过。**

已锁定的出场人物(只能引用这些名字):{character_names}
已锁定的场景:{scene_name}

只输出 JSON:
{{"shots": [
  {{"shot_size": "远/全/中/近/特写", "camera": "机位/摄法(如 平视/仰拍/推镜)",
    "visual_prompt": "画面内容描述",
    "dialogue_lines": [{{"character_name": "人物名或留空(留空=旁白)", "text": "台词/旁白"}}],
    "blocking": [{{"character_name": "人物名", "position": "如 画面左侧", "facing": "如 面向"}}],
    "character_names": ["本镜出场人物名"],
    "duration_s": 5}}
]}}

这一场剧本:
{scene_text}"""


def _resolve_llm(llm: Any) -> Any:
    if llm is not None:
        return llm
    from obase.provider_registry import ProviderRegistry

    try:
        return ProviderRegistry.get().llm("qwen_cloud")
    except Exception:
        return ProviderRegistry.get().llm("default")


async def _call_llm_json(llm: Any, prompt: str) -> dict[str, Any]:
    # qwen_cloud/dashscope 适配器(hevi/providers/registry.py:_SyncLLMAdapter)在构造时就
    # 同步发出 HTTP 请求(不是真正的 async I/O)——`await llm(...)` 挡不住它,会把单线程
    # event loop 整个卡住到那次调用返回为止。这是本函数上一版并发化"名不副实"的根因:
    # generate_shot_list_draft 用 asyncio.gather 逐场发起调用,但只要 event loop 被卡住,
    # 所有 gather 出去的 task 依然只能一个个排队跑,总耗时=场数×单次调用耗时,场次一多
    # 照样堆到反向代理超时(甚至比超时更糟——曾实测卡满 8×120s 单次超时上限,挂起 16
    # 分钟没有任何响应)。把"构造 llm(...)"这一步扔进线程池,才是真并发。
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


def _fallback_shots_for_scene(scene, scene_idx: int) -> list[ShotListItem]:
    """LLM 失败时的兜底:整场只切一镜,叙述当旁白行,每句台词各自一行(character_name
    照抄剧本,至少台词不会丢——比整体失败强)。"""
    dialogue_lines = [
        ShotListDialogueLine(character_name=d.character_name, text=d.text) for d in scene.dialogue
    ]
    if scene.narration:
        dialogue_lines.insert(0, ShotListDialogueLine(character_name="", text=scene.narration))
    return [
        ShotListItem(
            shot_id=f"SH{scene_idx + 1:03d}_01",
            scene_no=scene.scene_no,
            visual_prompt=scene.event_summary or scene.narration,
            dialogue_lines=dialogue_lines,
            character_names=list(scene.characters_present),
            scene_name=scene.location,
            duration_s=5.0,
        )
    ]


async def _shots_for_scene(
    idx: int,
    scene: Any,
    *,
    resolved_llm: Any,
    character_names: set[str],
    scene_names: set[str],
) -> list[ShotListItem]:
    scene_text_lines = [f"第{scene.scene_no}场 {scene.time} {scene.location}"]
    if scene.narration:
        scene_text_lines.append(f"叙述:{scene.narration}")
    scene_text_lines.extend(f"{d.character_name}:{d.text}" for d in scene.dialogue)
    scene_text = "\n".join(scene_text_lines)

    prompt = _SHOT_LIST_PROMPT.format(
        character_names="、".join(scene.characters_present) or "(无)",
        scene_name=scene.location or "(未定)",
        scene_text=scene_text,
    )
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning(
            "shot list draft LLM failed for scene %d, using fallback: %s", scene.scene_no, e
        )
        data = {}

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        return _fallback_shots_for_scene(scene, idx)

    shots: list[ShotListItem] = []
    for j, raw in enumerate(raw_shots):
        if not isinstance(raw, dict):
            continue
        raw_dialogue = raw.get("dialogue_lines") or []
        dialogue_lines = [
            ShotListDialogueLine(
                character_name=str(d.get("character_name") or "").strip(),
                text=str(d.get("text") or "").strip(),
            )
            for d in raw_dialogue
            if isinstance(d, dict) and str(d.get("text") or "").strip()
        ]
        raw_blocking = raw.get("blocking") or []
        blocking = [
            ShotBlocking(
                character_name=str(b.get("character_name") or "").strip(),
                position=str(b.get("position") or "").strip(),
                facing=str(b.get("facing") or "").strip(),
            )
            for b in raw_blocking
            if isinstance(b, dict) and str(b.get("character_name") or "").strip()
        ]
        shot_character_names = [
            str(c).strip()
            for c in (raw.get("character_names") or [])
            if str(c).strip() in character_names
        ]
        shot_scene_name = str(raw.get("scene_name") or scene.location).strip()
        if shot_scene_name not in scene_names and scene.location in scene_names:
            shot_scene_name = scene.location

        shots.append(
            ShotListItem(
                shot_id=f"SH{idx + 1:03d}_{j + 1:02d}",
                scene_no=scene.scene_no,
                shot_size=str(raw.get("shot_size") or "").strip(),
                camera=str(raw.get("camera") or "").strip(),
                visual_prompt=str(raw.get("visual_prompt") or "").strip(),
                dialogue_lines=dialogue_lines,
                blocking=blocking,
                character_names=shot_character_names,
                scene_name=shot_scene_name,
                duration_s=float(raw.get("duration_s") or 5.0),
            )
        )
    return shots


async def generate_shot_list_draft(
    *, screenplay: Screenplay, design_list: DesignList, llm: Any = None
) -> ShotList:
    """锁定 Screenplay + DesignList → ShotList 草稿,逐场切镜头。每场一次 LLM 调用
    (而非整部剧本一次,让单场失败只退化那一场,不拖累全片),场与场之间并发调用——
    锁定②③④三级串在一个 HTTP 请求里,场次一多顺序调用会把请求拖到反向代理超时
    (线上曾实测触发 Cloudflare 524)。"""
    resolved_llm = _resolve_llm(llm)
    character_names = {c.name for c in design_list.characters}
    scene_names = {s.name for s in design_list.scenes}

    per_scene = await asyncio.gather(
        *(
            _shots_for_scene(
                idx,
                scene,
                resolved_llm=resolved_llm,
                character_names=character_names,
                scene_names=scene_names,
            )
            for idx, scene in enumerate(screenplay.scenes)
        )
    )
    all_shots = [shot for scene_shots in per_scene for shot in scene_shots]
    return ShotList(shots=all_shots)
