"""SPEC-003 ④分镜头剧本 —— 锁定 Screenplay + DesignList → ShotList 草稿。

这是主线"只有旁白没对白"崩坏症状的直接根治点:把每一场切成镜头序列,**台词行必须显式标注
speaker(哪个角色说)**,而不是把整场叙述文字囫囵吞枣丢给配音。
"""

from __future__ import annotations

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
    resp = await llm(messages=[{"role": "user", "content": prompt}], max_tokens=4096)
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


async def generate_shot_list_draft(
    *, screenplay: Screenplay, design_list: DesignList, llm: Any = None
) -> ShotList:
    """锁定 Screenplay + DesignList → ShotList 草稿,逐场切镜头。每场一次 LLM 调用
    (而非整部剧本一次,让单场失败只退化那一场,不拖累全片)。"""
    resolved_llm = _resolve_llm(llm)
    character_names = {c.name for c in design_list.characters}
    scene_names = {s.name for s in design_list.scenes}

    all_shots: list[ShotListItem] = []
    for idx, scene in enumerate(screenplay.scenes):
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
            all_shots.extend(_fallback_shots_for_scene(scene, idx))
            continue

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

            all_shots.append(
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

    return ShotList(shots=all_shots)
