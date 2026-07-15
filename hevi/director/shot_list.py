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

_SHOT_LIST_PROMPT = """你是电影分镜师。把下面这一场剧本切成**有电影语言的镜头序列**(通常 4-8 镜)。

**电影不是一路大头对白。一场戏要有三类镜头,穿插着来:**
1. **建场镜头(动作镜头,无对白)**:开场先交代环境和人物在干什么——比如"远景:宫廷茅厕外
   窄廊,豫让扮成刑徒,低头提着石灰桶进来,警惕地环顾"。dialogue_lines 留空,visual_prompt
   写清楚**画面里正在发生的动作**(谁在干什么),不是写旁白台词。
2. **动作镜头(无对白)**:推进剧情的动作——"赵襄子带着两名侍卫从廊子那头走来""侍卫一把
   拽住豫让的胳膊,从他袖中搜出匕首""豫让被按倒在地"。同样 dialogue_lines 留空,
   visual_prompt 写动作。
3. **对白镜头**:人物开口说话的镜头。**每一句人物对白必须原样落到某个镜头的 dialogue_lines
   里并标出说话人(character_name)。**

**硬性要求:**
- 开场至少一个建场/动作镜头(别一上来就是大头怼脸说话)。
- 关键情节(如刺杀、擒拿、搜身)要用**动作镜头**演出来,别只靠台词交代。
- 非对白镜头的 visual_prompt 必须是**具体的画面动作描述**,绝不是"旁白:xxx"这种念白文字。
- 每场镜头数别贪多也别只有对白,按剧情节奏来。

**实体名硬规则(治"人物/场景乱跳"):已锁定的人物/场景名字必须原样引用,禁止改写、
翻译、换同义词、加前后缀;禁止凭空新增没锁定过的角色或场景。镜头信息不全时,优先用
已锁定的人物/场景把画面补足,而不是发明新的。**

**动作弧 action_beats(治"人物没有连续的电影一样真实动作"):有明显肢体动作的镜头(尤其
动作镜),把这一镜的动作拆成一段**从触发到峰值到收束**的有序拍点,写进 action_beats——
按时间顺序,每个拍点一句具体画面动作。例:"张飞拔剑要自刎"→ ["张飞猛地抽剑架上脖颈",
"刘备扑上一把攥住剑身", "宝剑坠地,刘备紧抱住张飞"]。首拍是动作**刚触发**的瞬间,末拍是
**收束/结果**态。纯静态场景镜或纯对白镜没有动作弧时,action_beats 留空数组。**

**对谁说 target_name(§H,驱动视线):每句对白标出**说给谁听**(target_name)——A 对 B 说话,
target_name 就是 B 的名字(必须是已锁定人物名)。对众/独白/自言自语没有明确受话者时留空。**

**visual_prompt 编写口径(§F,降镜头间漂移):按固定顺序组织——①景别/机位/运镜 ②场景环境
③主体人物或关键对象 ④动作与状态 ⑤氛围情绪 ⑥必要风格收束。优先写**主角色**、优先建立
**主场景**;道具只在进入主动作或构图焦点时才重点写,不要每样都平均铺陈成流水账。**

已锁定的出场人物(只能引用这些名字):{character_names}
已锁定的场景:{scene_name}

只输出 JSON:
{{"shots": [
  {{"shot_size": "远/全/中/近/特写", "camera": "机位/摄法(如 平视/仰拍/推镜/手持跟拍)",
    "visual_prompt": "按①景别②场景③主体④动作⑤氛围⑥风格的顺序组织(动作镜写动作不写台词)",
    "action_beats": ["触发拍:具体画面动作", "峰值拍:...", "收束拍:..."],
    "dialogue_lines": [{{"character_name": "人物名(动作镜头留空数组)", "text": "台词",
        "target_name": "受话人名(对谁说,无明确对象留空)"}}],
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


# INC-001 §K.1 质量闸:visual_prompt/action_beats 只描述画面本身,不该混入参考图映射说明。
_CONTAM_MARKERS = ("图1", "图2", "图3", "图片内容说明", "参考图")
_QC_CORRECTION = (
    "\n\n**修正要求:上次输出把参考图映射说明混进了画面描述。visual_prompt 与 action_beats "
    "只描述画面本身,绝不能出现「图1/图2/参考图/图片内容说明」这类工程说明文字。**"
)


def _contaminated(data: dict[str, Any]) -> bool:
    """§K.1:LLM 输出是否混入「图1/图2/图片内容说明/参考图」这类参考图映射说明。"""
    for raw in data.get("shots") or []:
        if not isinstance(raw, dict):
            continue
        blob = str(raw.get("visual_prompt") or "") + " ".join(
            str(b) for b in (raw.get("action_beats") or [])
        )
        if any(m in blob for m in _CONTAM_MARKERS):
            return True
    return False


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

    # §K.1 轻量质量闸:输出混入参考图映射说明 → 带修正要求重试一次,再决定落库。
    if _contaminated(data):
        logger.info("shot list scene %d 输出含参考图映射污染,带修正重试一次", scene.scene_no)
        try:
            retry = await _call_llm_json(resolved_llm, prompt + _QC_CORRECTION)
            if retry.get("shots"):
                data = retry
        except Exception as e:
            logger.warning("shot list scene %d QC 修正重试失败,沿用原输出: %s", scene.scene_no, e)

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
                target_name=str(d.get("target_name") or "").strip(),
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
        action_beats = [str(b).strip() for b in (raw.get("action_beats") or []) if str(b).strip()]
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
                action_beats=action_beats,
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
