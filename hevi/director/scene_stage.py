"""SPEC-004 ③.5 场面调度 —— 锁定的 ②Screenplay(单场) + ③DesignList → SceneStage 草案。

这是"六份 spec 之后还是啥也不是"的结构性根治点:此前剧本直接跳到分镜,每个镜头在自己的
prompt 里重新想象一遍空间,人一多就互相矛盾。SceneStage 让每场戏先"立起来"(blocking +
轴线 + 注意力 + 机位),该场所有镜头从同一场事实切视角。**这里只产草稿,不锁定——锁定是人
在 Construction-First 下攻击落位/注意力/机位后的动作(见 director_pipeline.py scene-stage/lock)。**

v1 设计决策:
- **beats 以对白行确定性锚定**(一句对白一拍,btNNN)。把 beat_ids 连同对白喂给 LLM,让它
  产出 space_map/blocking/axis/attention_script/coverage_plan 时引用这些 beat_id。非对白拍
  (纯动作/进场)留 v2——G-S1 是 3 人对话戏,对白拍就是骨架。
- **sightlines 从对白 speaker→target 确定性派生**(INC-001 §H 升格为主要派生源,权威)。
  LLM 只补无对白时刻的视线(assumed=True),人审核。
- 俯视图不让 AI 画:zones 结构化,layout_sketch 需要时从 zones 派生(§7 单一真相源)。
- LLM/解析失败不阻断:确定性兜底出一个最小可锁 SceneStage(空描述好过整体失败)。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.director.design_list import _call_llm_json, _resolve_llm
from hevi.director.pipeline_schemas import (
    AttentionBeat,
    AxisShift,
    BlockingMove,
    CameraSetup,
    CoveragePlan,
    DesignList,
    InitialPosition,
    SceneAxis,
    SceneBeat,
    SceneBlocking,
    SceneLandmark,
    SceneSpaceMap,
    SceneStage,
    SceneStageSet,
    SceneZone,
    ScreenplayScene,
    ShotList,
    ShotListItem,
    Sightline,
)

logger = logging.getLogger(__name__)

_SCENE_STAGE_PROMPT = """你是电影场面调度师(blocking)。下面是一场戏的剧本、该场的人物/场景/道具
资产,以及已经按对白切好的节拍序列(beats,每拍一个 beat_id)。请把这场戏"立起来":定死每个
人物站哪、朝向哪、何时移动;定死本场主轴线(180°规则基准);预谋每一拍观众该看谁(注意力);
架好覆盖机位。**机位是对着"已存在的调度事实"架的,不是重新想象空间。**

约束:
- 所有 char_id 必须用给定的人物名,不要发明新人物。
- zone 是空间关键区域(如 门口/窗边/桌旁),landmark 引用给定道具名。
- attention_script 和 coverage_plan 的 at_beat / serves_beats 必须引用给定的 beat_id。
- axis_side 必须声明机位在主轴哪一侧(left 或 right)。
- 每个 beat 至少被 2 个 camera_setup 覆盖(留剪辑余地)。
- **朝向/机位用角度(SPEC-004 v2,让朝向落到画面)**:每个 initial_position 给 facing_deg=角色
  朝向(0=面向观众/正前, 90=面向画右, 180=背对观众, 270=面向画左);每个 camera_setup 给
  azimuth_deg=机位所在方位(0=正面/观众席, 90=画右侧, 180=背后, 270=画左侧)。对话中两人通常
  互相面对:画左的人 facing≈90、画右的人 facing≈270。拿不准就按此约定给整数。

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

第{scene_no}场 {time} {location}
出场:{characters_present}
叙述:{narration}
对白节拍:
{beats_text}

该场资产:
人物:{characters_text}
场景:{scenes_text}
道具:{props_text}"""


def _derive_beats(scene: ScreenplayScene) -> list[SceneBeat]:
    """对白行 → 确定性节拍骨架(一句对白一拍)。trigger=对白文本,dialogue_ref=speaker→target。"""
    beats: list[SceneBeat] = []
    order = 0
    for d in scene.dialogue:
        speaker = (d.character_name or "").strip()
        if not speaker:
            continue  # 旁白不成拍(数字人管线无旁白,见 tongjian_render)
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


def _derive_dialogue_sightlines(
    scene: ScreenplayScene, beats: list[SceneBeat], present: set[str]
) -> list[Sightline]:
    """INC-001 §H 升格:对白 speaker→target 确定性派生视线(权威源,assumed=False)。
    target 须是本场在场角色且非说话人本人,否则不成视线(与 tongjian_render 的校验一致)。"""
    sightlines: list[Sightline] = []
    dlg_beats = list(beats)  # beats 已按对白 1:1 生成,顺序对齐
    i = 0
    for d in scene.dialogue:
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


def _parse_positions(raw: Any, present: set[str]) -> list[InitialPosition]:
    out: list[InitialPosition] = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        cid = str(p.get("char_id") or "").strip()
        if cid not in present:
            continue
        out.append(
            InitialPosition(
                char_id=cid,
                zone_id=str(p.get("zone_id") or "").strip(),
                facing=str(p.get("facing") or "").strip(),
                posture=str(p.get("posture") or "").strip(),
                facing_deg=_parse_deg(p.get("facing_deg")),
            )
        )
    return out


def _parse_deg(v: Any) -> int | None:
    """角度解析:整数化并归一到 0-359;非数/空 → None(渲染层据此退回正面 2D 真照)。"""
    if v is None or v == "":
        return None
    try:
        return round(float(v)) % 360
    except Exception:
        return None


def _parse_camera_setup(raw: Any, beat_ids: set[str], present: set[str]) -> CameraSetup | None:
    if not isinstance(raw, dict):
        return None
    sid = str(raw.get("setup_id") or "").strip()
    if not sid:
        return None
    return CameraSetup(
        setup_id=sid,
        position=str(raw.get("position") or "").strip(),
        axis_side=str(raw.get("axis_side") or "").strip(),
        shot_size=str(raw.get("shot_size") or "").strip(),
        serves_beats=[b for b in (raw.get("serves_beats") or []) if str(b) in beat_ids],
        subjects=[s for s in (raw.get("subjects") or []) if str(s) in present],
        azimuth_deg=_parse_deg(raw.get("azimuth_deg")),
    )


async def generate_scene_stage_draft(
    *, scene: ScreenplayScene, design_list: DesignList, llm: Any = None
) -> SceneStage:
    """锁定 Screenplay(单场)+ DesignList → SceneStage 草案。

    beats 与 dialogue-sightlines 确定性生成(不靠 LLM);space_map/blocking(落位/动线)/axis/
    attention/coverage 由 LLM 出草案,失败则确定性兜底(最小可锁)。整体标 assumed=True(人未攻击前)。
    """
    present = {c for c in (scene.characters_present or []) if c}
    beats = _derive_beats(scene)
    beat_ids = {b.beat_id for b in beats}
    dialogue_sightlines = _derive_dialogue_sightlines(scene, beats, present)

    resolved_llm = _resolve_llm(llm)
    prompt = _SCENE_STAGE_PROMPT.format(
        scene_no=scene.scene_no,
        time=scene.time,
        location=scene.location,
        characters_present="、".join(scene.characters_present),
        narration=scene.narration or "(无)",
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
        logger.warning("scene stage draft LLM failed, using fallback: %s", e)
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

    # ── blocking(落位/动线 by LLM;sightlines = 对白派生 + LLM 补的无对白视线)──────
    bl_raw = data.get("blocking") if isinstance(data.get("blocking"), dict) else {}
    initial_positions = _parse_positions(bl_raw.get("initial_positions"), present)
    # zone 引用不硬拦(LLM 可能用未声明 zone,人审时补)——校验留给 lint 层。
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
    # LLM 补的无对白视线(assumed=True),对白视线以确定性派生为准(去重:同 beat+char 保留派生)
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

    # ── axis ─────────────────────────────────────────────────────────────────
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

    # ── 确定性兜底(LLM 全空时保证最小可锁)──────────────────────────────────
    if not axis.primary_axis and len(present) >= 2:
        two = list(scene.characters_present)[:2]
        axis = SceneAxis(primary_axis=two, side_convention=f"{two[0]}恒在画左,{two[1]}恒在画右")
    if not attention_script and beats:
        # 无注意力脚本 → 每拍焦点默认落在说话人(speaking)
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
            initial_positions=[InitialPosition(char_id=c) for c in scene.characters_present if c],
            moves=blocking.moves,
            sightlines=blocking.sightlines,
        )

    return SceneStage(
        scene_ref=scene.scene_no,
        space_map=space_map,
        beats=beats,
        blocking=blocking,
        axis=axis,
        attention_script=attention_script,
        coverage_plan=coverage_plan,
        assumed=True,
    )


# ── 阶段 3:分镜 ↔ 场事实的确定性链接(SPEC-004 §3.1)────────────────────────────
#
# v1 用确定性链接而非改写 shot_list 的 LLM prompt(降风险,不碰已部署生成逻辑):SceneStage
# 的 beats 是对白锚定的(trigger=对白文本),所以镜头覆盖哪几拍可由"匹配镜头的对白行→beats"
# 精确派生(比 LLM 选更准、无幻觉)。camera_setup 按 serves_beats/subjects 重叠度择优。
# DP1 原设想"LLM 判断哪几拍+机位";这里改为确定性派生,作为 v1 简化,LLM-choice 留 v2。


def _match_beats_for_shot(shot: ShotListItem, stage: SceneStage) -> list[str]:
    """镜头的对白行 → SceneStage 的 beat_id 列表(按对白文本+说话人精确匹配,保序去重)。"""
    matched: list[str] = []
    for dl in shot.dialogue_lines:
        speaker = (dl.character_name or "").strip()
        text = (dl.text or "").strip()
        if not speaker or not text:
            continue  # 旁白行不成拍
        for b in stage.beats:
            if b.beat_id in matched:
                continue
            if b.trigger == text and b.dialogue_ref.split("→")[0] == speaker:
                matched.append(b.beat_id)
                break
    return matched


def _pick_camera_setup(shot: ShotListItem, stage: SceneStage, beat_range: list[str]) -> str:
    """择优机位:优先 serves_beats 覆盖到本镜 beats 的;同分时偏好 subjects 与本镜出场角色重叠多的。
    无覆盖机位则退回第一个 setup(或 master)。都没有则空。"""
    beat_set = set(beat_range)
    shot_chars = set(shot.character_names or [])
    best, best_score = "", -1
    for cs in stage.coverage_plan.setups:
        covers = len(beat_set & set(cs.serves_beats))
        if covers == 0:
            continue
        score = covers * 10 + len(shot_chars & set(cs.subjects))
        if score > best_score:
            best, best_score = cs.setup_id, score
    if best:
        return best
    if stage.coverage_plan.setups:
        return stage.coverage_plan.setups[0].setup_id
    return stage.coverage_plan.master.setup_id if stage.coverage_plan.master else ""


_INTENSITY_ZH = {
    "exclusive": "独占前景、浅景深虚化他人",
    "primary": "主焦点、保留环境",
    "shared": "群像并置",
}

# SPEC-004 v2:相机方位角 − 角色朝向 → 相机看到角色的哪个视图。delta 量化到最近 90°:
# 0=front(相机在角色正对的方向)/ 90=right / 180=back / 270=left。left/right 是约定(跟
# TripoSR 视图标签对齐),若实测反了改这一行即可。
_VIEW_BY_DELTA = ("front", "right", "back", "left")


def resolve_subject_view(cam_azimuth_deg: int | None, char_facing_deg: int | None) -> str:
    """这镜的相机看向该角色时,看到 Subject3D 的哪个视图(front/left/right/back)。
    任一角度缺失 → "front"(退回 2D 真照,身份最强,不冒 3D 帧身份变弱的险)。"""
    if cam_azimuth_deg is None or char_facing_deg is None:
        return "front"
    delta = round(((cam_azimuth_deg - char_facing_deg) % 360) / 90) % 4
    return _VIEW_BY_DELTA[delta]


def compute_shot_views(
    shot_list: ShotList, scene_stage_set: SceneStageSet
) -> dict[str, dict[str, str]]:
    """SPEC-004 v2 桥接:每镜每出场角色该用哪个 Subject3D 视图(shot_id → {char_id: view})。
    从镜头的 camera_setup(azimuth_deg)+ 该角色 blocking 落位(facing_deg)几何算出。角度缺失
    的角色算出 "front"(渲染层据此退回 2D 真照)。未接场事实的镜头不产条目。"""
    stage_by_ref = {s.scene_ref: s for s in scene_stage_set.stages}
    out: dict[str, dict[str, str]] = {}
    for shot in shot_list.shots:
        stage = stage_by_ref.get(shot.scene_stage_ref) if shot.scene_stage_ref is not None else None
        if stage is None:
            continue
        setups = {c.setup_id: c for c in stage.coverage_plan.setups}
        if stage.coverage_plan.master:
            setups.setdefault(stage.coverage_plan.master.setup_id, stage.coverage_plan.master)
        cam = setups.get(shot.camera_setup_ref)
        azimuth = cam.azimuth_deg if cam else None
        facing_by_char = {p.char_id: p.facing_deg for p in stage.blocking.initial_positions}
        views = {
            cid: resolve_subject_view(azimuth, facing_by_char.get(cid))
            for cid in (shot.character_names or [])
        }
        out[shot.shot_id] = views
    return out


def project_shot_space(stage: SceneStage, shot: ShotListItem) -> str:
    """SPEC-004 §3.2 桥接层确定性投影:从 SceneStage + 镜头的场事实引用,算出"这机位这一拍看到
    什么"的空间文本(落位/朝向 + 焦点 + 画面正方向)。**纯确定性字符串工程,不经 LLM**——这正是
    要消灭"每镜各自想象空间"的地方。输出拼进关键帧 prompt 的空间项(§F.1 口径,排相貌前)。"""
    zone_name = {z.zone_id: (z.name or z.zone_id) for z in stage.space_map.zones}
    pos_by_char = {p.char_id: p for p in stage.blocking.initial_positions}
    # 本镜 beat_range 内发生的移动 → 用移动后的落位(动线)
    beat_set = set(shot.beat_range)
    moved_to = {
        m.char_id: m.to_zone for m in stage.blocking.moves if m.at_beat in beat_set and m.to_zone
    }

    blocking_segs: list[str] = []
    for c in shot.character_names:
        p = pos_by_char.get(c)
        zone = moved_to.get(c) or (p.zone_id if p else "")
        seg = c
        if zone:
            seg += f"在{zone_name.get(zone, zone)}"
        if p and p.facing:
            seg += f"、{p.facing}"
        if seg != c:  # 只在有落位信息时才写
            blocking_segs.append(seg)

    attn = next((a for a in stage.attention_script if a.at_beat == shot.attention_ref), None)
    focus_text = ""
    if attn and attn.focus_target:
        focus_text = f"焦点在{attn.focus_target}({_INTENSITY_ZH.get(attn.intensity, '主焦点')})"

    segs = [s for s in ["；".join(blocking_segs), focus_text, stage.axis.side_convention] if s]
    return "；".join(segs)


def link_shots_to_scene_stage(shot_list: ShotList, scene_stage_set: SceneStageSet) -> ShotList:
    """确定性填充每个 ShotListItem 的 4 个场事实引用(scene_stage_ref/beat_range/
    camera_setup_ref/attention_ref)。找不到对应 SceneStage 的镜头原样返回(向后兼容)。
    attention_ref = beat_range 里第一个有 attention_script 条目的 beat(带出 focus_target)。"""
    stage_by_ref = {s.scene_ref: s for s in scene_stage_set.stages}
    linked = []
    for shot in shot_list.shots:
        stage = stage_by_ref.get(shot.scene_no)
        if stage is None:
            linked.append(shot)
            continue
        beat_range = _match_beats_for_shot(shot, stage)
        attn_beats = {a.at_beat for a in stage.attention_script}
        attention_ref = next(
            (b for b in beat_range if b in attn_beats), beat_range[0] if beat_range else ""
        )
        camera_setup_ref = _pick_camera_setup(shot, stage, beat_range)
        linked.append(
            shot.model_copy(
                update={
                    "scene_stage_ref": stage.scene_ref,
                    "beat_range": beat_range,
                    "camera_setup_ref": camera_setup_ref,
                    "attention_ref": attention_ref,
                }
            )
        )
    return ShotList(shots=linked)
