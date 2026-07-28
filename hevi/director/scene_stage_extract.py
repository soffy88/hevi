"""SPEC-006 ②.5 SceneStage 抽取器 —— Scene Script(逐段时间轴)→ SceneStage(结构影子)。

V2 角色反转的落点:SceneStage 不再是"AI 立起来这场戏"的生成源(那是 scene_stage.py 的
`generate_scene_stage_draft`,V1 用于剧本 → 场面调度的创作),而是"从已经写好的时间轴文档
抽取已隐含的场面调度事实"——产出的 SceneStage 结构上与 `generate_scene_stage_draft` 完全
等价(同一 Pydantic 类型),可以原样喂给既有 `scene_stage_lint.py::lint_scene_stage()`,
lint 函数本身零改动。

混合方案:
- **确定性部分**(beats/dialogue-sightlines):镜像 `scene_stage.py::_derive_beats`/
  `_derive_dialogue_sightlines`,源从 `ScreenplayScene.dialogue` 换成 Scene Script 逐段
  对白展开。不直接调用原函数(签名硬编码吃 ScreenplayScene),不碰 V1 已上线代码,同构镜像
  一份保持 beat_id 格式/生成规则完全一致。
- **推断部分**(space_map/blocking 落位/axis/attention_script/coverage_plan):正则做不到
  从叙事段落推断空间几何关系,用 LLM,但 prompt 框架是"抽取口吻"("已经隐含的事实,不要
  发明时间轴没写的空间关系")而非 scene_stage.py 的"创作口吻"("把这场戏立起来")。
  解析复用 `scene_stage.py::_parse_positions`/`_parse_deg`/`_parse_camera_setup`(只依赖
  dict+集合,跟数据来自 Screenplay 还是 Scene Script 无关,可以原样导入)。

**关键约束**:beat 匹配靠 `beat.trigger == 台词文本`逐字相等(`scene_stage.py::
_match_beats_for_shot`)。这要求 Scene Script 生成器(`scene_script.py`)产出的
`dialogue.text` 与叙事文本逐字一致——这里只是消费方,约束的强制点在生成器的 prompt。

这是 G-V2 垂直切片(spec §5)②的抽取器部分,纯文本 LLM 调用。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.director.design_list import _call_llm_json, _resolve_llm
from hevi.director.pipeline_schemas import (
    AttentionBeat,
    AxisShift,
    BlockingMove,
    CoveragePlan,
    DesignList,
    InitialPosition,
    SceneAxis,
    SceneBeat,
    SceneBlocking,
    SceneLandmark,
    SceneScript,
    SceneScriptDialogueLine,
    SceneSpaceMap,
    SceneStage,
    SceneZone,
    Sightline,
)
from hevi.director.scene_stage import _parse_camera_setup, _parse_positions

logger = logging.getLogger(__name__)

_SCENE_STAGE_EXTRACT_PROMPT = """你是场记。下面是一场戏已经写好的逐段时间轴(每段是【动作+
摄像机行为一体】的连续描述,已经决定了怎么拍),不是待创作的剧本。请把其中**已经隐含**的
场面调度事实抽取出来——只抽取时间轴文本里明确写到或能直接推断的内容,**不要发明时间轴
没写的站位/机位/视线**。

约束:
- 所有 char_id 必须用给定的人物名,不要发明新人物。
- zone 是空间关键区域(如 门口/窗边/桌旁),landmark 引用给定道具名。
- attention_script 和 coverage_plan 的 at_beat / serves_beats 必须引用给定的 beat_id。
- axis_side 必须声明机位在主轴哪一侧(left 或 right)。
- 每个 beat 尽量被 ≥2 个 camera_setup 覆盖(留剪辑余地),但**不要为了凑数编造时间轴没有
  依据的机位**——时间轴信息不足以支撑时,按能推断出的最合理配置来,宁可少而准。
- **朝向/机位用角度**:每个 initial_position 给 facing_deg=角色朝向(0=面向观众/正前,
  90=面向画右, 180=背对观众, 270=面向画左);每个 camera_setup 给 azimuth_deg=机位所在
  方位(0=正面/观众席, 90=画右侧, 180=背后, 270=画左侧)。

只输出 JSON(字段说明见约束):
{{"space_map": {{
    "zones": [{{"zone_id": "z1", "name": "区域名", "rel_position": "左上/中心/右下等"}}],
    "landmarks": [{{"name": "道具名", "zone_id": "z1"}}]}},
 "blocking": {{
    "initial_positions": [{{
      "char_id": "人物名", "zone_id": "z1", "facing": "朝向", "facing_deg": 90,
      "posture": "姿态"}}],
    "moves": [{{
      "char_id": "人物名", "at_beat": "beat_id", "from_zone": "z1", "to_zone": "z2",
      "action": "动作"}}],
    "sightlines": [{{
      "at_beat": "beat_id", "char_id": "人物名", "looking_at": "人物名或道具", "assumed": true}}]}},
 "axis": {{
    "primary_axis": ["人物甲", "人物乙"], "side_convention": "甲恒在画左,乙恒在画右",
    "axis_shifts": [{{
      "at_beat": "beat_id", "new_axis": ["人物甲", "人物丙"], "reason": "转移理由"}}]}},
 "attention_script": [{{
    "at_beat": "beat_id", "focus_target": "人物名",
    "reason": "speaking/reacting/about_to_speak/reveal/entrance/key_action",
    "transition": "cut/pan/push/rack_focus/follow",
    "intensity": "exclusive/primary/shared"}}],
 "coverage_plan": {{
    "master": {{
      "setup_id": "master", "position": "机位描述", "axis_side": "left", "shot_size": "全景",
      "serves_beats": ["beat_id"], "subjects": ["人物名"]}},
    "setups": [{{
      "setup_id": "s1", "position": "机位描述", "axis_side": "left", "azimuth_deg": 0,
      "shot_size": "中景", "serves_beats": ["beat_id"], "subjects": ["人物名"]}}]}}}}

第{scene_no}场 逐段时间轴:
{timeline_text}

对白节拍:
{beats_text}

该场资产:
人物:{characters_text}
场景:{scenes_text}
道具:{props_text}"""


def _flatten_dialogue(scene_script: SceneScript) -> list[SceneScriptDialogueLine]:
    return [d for seg in scene_script.segments for d in seg.dialogue if d.character_name]


def _derive_beats_from_script(scene_script: SceneScript) -> list[SceneBeat]:
    """镜像 scene_stage._derive_beats,源从 ScreenplayScene.dialogue 换成 SceneScript
    逐段对白展开(保序),beat_id 格式(btNNN)/生成规则(一句对白一拍)完全一致。"""
    beats: list[SceneBeat] = []
    order = 0
    for d in _flatten_dialogue(scene_script):
        speaker = (d.character_name or "").strip()
        if not speaker:
            continue
        order += 1
        target = (d.target_name or "").strip()
        ref = f"{speaker}→{target}" if target else speaker
        beats.append(
            SceneBeat(
                beat_id=f"bt{order:03d}",
                order=order,
                trigger=(d.text or "").strip(),
                dialogue_ref=ref,
            )
        )
    return beats


def _derive_dialogue_sightlines_from_script(
    scene_script: SceneScript, beats: list[SceneBeat], present: set[str]
) -> list[Sightline]:
    """镜像 scene_stage._derive_dialogue_sightlines,同上。"""
    sightlines: list[Sightline] = []
    dlg_beats = list(beats)
    i = 0
    for d in _flatten_dialogue(scene_script):
        speaker = (d.character_name or "").strip()
        if not speaker:
            continue
        beat = dlg_beats[i] if i < len(dlg_beats) else None
        i += 1
        target = (d.target_name or "").strip()
        if not beat or not target or target not in present or target == speaker:
            continue
        sightlines.append(
            Sightline(at_beat=beat.beat_id, char_id=speaker, looking_at=target, assumed=False)
        )
    return sightlines


def _timeline_text(scene_script: SceneScript) -> str:
    return (
        "\n".join(
            f"[{seg.t_start_s:.1f}-{seg.t_end_s:.1f}s] {seg.narrative_text}"
            for seg in scene_script.segments
        )
        or "(无时间轴)"
    )


async def extract_scene_stage_from_script(
    *, scene_script: SceneScript, design_list: DesignList, llm: Any = None
) -> SceneStage:
    """Scene Script 时间轴 → SceneStage 结构影子。beats/dialogue-sightlines 确定性镜像
    scene_stage.py 同名函数;space_map/blocking 落位/axis/attention/coverage 由 LLM 从完整
    时间轴文本抽取(抽取口吻,非创作口吻),解析复用 scene_stage._parse_positions/_parse_deg/
    _parse_camera_setup。产出的 SceneStage 结构上与 generate_scene_stage_draft 的产物完全
    等价(同一 Pydantic 类型),可直接喂 lint_scene_stage()。"""
    present = {c for c in (scene_script.characters_present or []) if c}
    beats = _derive_beats_from_script(scene_script)
    beat_ids = {b.beat_id for b in beats}
    dialogue_sightlines = _derive_dialogue_sightlines_from_script(scene_script, beats, present)

    resolved_llm = _resolve_llm(llm)
    prompt = _SCENE_STAGE_EXTRACT_PROMPT.format(
        scene_no=scene_script.scene_ref,
        timeline_text=_timeline_text(scene_script),
        beats_text="\n".join(f"{b.beat_id}: {b.dialogue_ref} —— {b.trigger}" for b in beats)
        or "(本场无对白)",
        characters_text="；".join(
            f"{c.name}({c.appearance})" for c in design_list.characters if c.name in present
        )
        or "(无)",
        scenes_text="；".join(f"{s.name}({s.environment})" for s in design_list.scenes if s.name)
        or "(无)",
        props_text="、".join(p.name for p in design_list.props if p.name) or "(无)",
    )
    try:
        data = await _call_llm_json(resolved_llm, prompt)
    except Exception as e:
        logger.warning("scene stage extract LLM failed, using fallback: %s", e)
        data = {}

    # ── space_map ──────────────────────────────────────────────────────────
    sm_raw = data.get("space_map") if isinstance(data.get("space_map"), dict) else {}
    zones = [
        SceneZone(
            zone_id=str(z.get("zone_id") or "").strip(),
            name=str(z.get("name") or "").strip(),
            rel_position=str(z.get("rel_position") or "").strip(),
        )
        for z in (sm_raw.get("zones") or [])
        if isinstance(z, dict) and str(z.get("zone_id") or "").strip()
    ]
    prop_names = {p.name for p in design_list.props if p.name}
    landmarks = [
        SceneLandmark(
            name=str(lm.get("name") or "").strip(), zone_id=str(lm.get("zone_id") or "").strip()
        )
        for lm in (sm_raw.get("landmarks") or [])
        if isinstance(lm, dict) and str(lm.get("name") or "").strip() in prop_names
    ]
    space_map = SceneSpaceMap(zones=zones, landmarks=landmarks)

    # ── blocking ───────────────────────────────────────────────────────────
    bl_raw = data.get("blocking") if isinstance(data.get("blocking"), dict) else {}
    initial_positions = _parse_positions(bl_raw.get("initial_positions"), present)
    moves = [
        BlockingMove(
            char_id=str(m.get("char_id") or "").strip(),
            at_beat=str(m.get("at_beat") or "").strip()
            if str(m.get("at_beat")) in beat_ids
            else "",
            from_zone=str(m.get("from_zone") or "").strip(),
            to_zone=str(m.get("to_zone") or "").strip(),
            action=str(m.get("action") or "").strip(),
        )
        for m in (bl_raw.get("moves") or [])
        if isinstance(m, dict) and str(m.get("char_id") or "").strip() in present
    ]
    derived_keys = {(s.at_beat, s.char_id) for s in dialogue_sightlines}
    llm_sightlines = [
        Sightline(
            at_beat=str(s.get("at_beat") or "").strip(),
            char_id=str(s.get("char_id") or "").strip(),
            looking_at=str(s.get("looking_at") or "").strip(),
            assumed=True,
        )
        for s in (bl_raw.get("sightlines") or [])
        if isinstance(s, dict)
        and str(s.get("char_id") or "").strip() in present
        and (str(s.get("at_beat") or "").strip(), str(s.get("char_id") or "").strip())
        not in derived_keys
    ]
    blocking = SceneBlocking(
        initial_positions=initial_positions,
        moves=moves,
        sightlines=dialogue_sightlines + llm_sightlines,
    )

    # ── axis ───────────────────────────────────────────────────────────────
    ax_raw = data.get("axis") if isinstance(data.get("axis"), dict) else {}
    primary_axis = [a for a in (ax_raw.get("primary_axis") or []) if str(a) in present][:2]
    axis_shifts = [
        AxisShift(
            at_beat=str(s.get("at_beat") or "").strip()
            if str(s.get("at_beat")) in beat_ids
            else "",
            new_axis=[a for a in (s.get("new_axis") or []) if str(a) in present][:2],
            reason=str(s.get("reason") or "").strip(),
        )
        for s in (ax_raw.get("axis_shifts") or [])
        if isinstance(s, dict)
    ]
    axis = SceneAxis(
        primary_axis=primary_axis,
        axis_shifts=axis_shifts,
        side_convention=str(ax_raw.get("side_convention") or "").strip(),
    )

    # ── attention_script ──────────────────────────────────────────────────────
    _valid_transition = {"cut", "pan", "push", "rack_focus", "follow"}
    _valid_intensity = {"exclusive", "primary", "shared"}
    attention_script = [
        AttentionBeat(
            at_beat=str(a.get("at_beat") or "").strip(),
            focus_target=str(a.get("focus_target") or "").strip(),
            reason=str(a.get("reason") or "").strip(),
            transition=(str(a.get("transition") or "cut").strip() or "cut")
            if str(a.get("transition") or "cut").strip() in _valid_transition
            else "cut",
            intensity=(str(a.get("intensity") or "primary").strip() or "primary")
            if str(a.get("intensity") or "primary").strip() in _valid_intensity
            else "primary",
        )
        for a in (data.get("attention_script") or [])
        if isinstance(a, dict) and str(a.get("at_beat") or "").strip() in beat_ids
    ]

    # ── coverage_plan ─────────────────────────────────────────────────────────
    cp_raw = data.get("coverage_plan") if isinstance(data.get("coverage_plan"), dict) else {}
    master = _parse_camera_setup(cp_raw.get("master"), beat_ids, present)
    setups = [
        cs
        for s in (cp_raw.get("setups") or [])
        if (cs := _parse_camera_setup(s, beat_ids, present)) is not None
    ]
    coverage_plan = CoveragePlan(master=master, setups=setups)

    # ── 确定性兜底(镜像 generate_scene_stage_draft,LLM 全空时保证最小可锁)──────
    if not axis.primary_axis and len(present) >= 2:
        two = list(scene_script.characters_present)[:2]
        axis = SceneAxis(primary_axis=two, side_convention=f"{two[0]}恒在画左,{two[1]}恒在画右")
    if not attention_script and beats:
        attention_script = [
            AttentionBeat(
                at_beat=b.beat_id,
                focus_target=b.dialogue_ref.split("→")[0],
                reason="speaking",
                transition="cut",
                intensity="primary",
            )
            for b in beats
        ]
    if not blocking.initial_positions:
        blocking = SceneBlocking(
            initial_positions=[
                InitialPosition(char_id=c) for c in scene_script.characters_present if c
            ],
            moves=blocking.moves,
            sightlines=blocking.sightlines,
        )

    return SceneStage(
        scene_ref=scene_script.scene_ref,
        space_map=space_map,
        beats=beats,
        blocking=blocking,
        axis=axis,
        attention_script=attention_script,
        coverage_plan=coverage_plan,
        assumed=True,
    )
