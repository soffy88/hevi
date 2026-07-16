"""SPEC-004 ③.5 场面调度 SceneStage 草案生成测试。

覆盖:beats/dialogue-sightlines 确定性生成(不靠 LLM)、LLM 草案解析(space_map/blocking/axis/
attention/coverage)、LLM 全空时的确定性兜底(最小可锁)、越界引用过滤(未在场角色/未知 beat_id)。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hevi.director.pipeline_schemas import (
    CameraSetup,
    CoveragePlan,
    DesignCharacter,
    DesignList,
    DesignProp,
    DesignScene,
    SceneStage,
    SceneStageSet,
    ScreenplayDialogueLine,
    ScreenplayScene,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
)
from hevi.director.scene_stage import generate_scene_stage_draft, link_shots_to_scene_stage


def _scene() -> ScreenplayScene:
    return ScreenplayScene(
        scene_no=3,
        time="黄昏",
        location="破客栈",
        characters_present=["王生", "老道", "店家"],
        narration="三人对峙。",
        dialogue=[
            ScreenplayDialogueLine(character_name="王生", text="求道长收留。", target_name="老道"),
            ScreenplayDialogueLine(character_name="老道", text="你受不得苦。", target_name="王生"),
            ScreenplayDialogueLine(character_name="店家", text="客官莫强求。", target_name="王生"),
        ],
    )


def _design() -> DesignList:
    return DesignList(
        characters=[
            DesignCharacter(name="王生", appearance="青年书生"),
            DesignCharacter(name="老道", appearance="白须道士"),
            DesignCharacter(name="店家", appearance="中年掌柜"),
        ],
        scenes=[DesignScene(name="破客栈", environment="昏暗客栈")],
        props=[DesignProp(name="油灯")],
    )


async def _draft(llm_json: dict) -> object:
    async def _fake(_llm, _prompt):
        return llm_json

    with patch("hevi.director.scene_stage._call_llm_json", side_effect=_fake):
        return await generate_scene_stage_draft(scene=_scene(), design_list=_design(), llm=object())


@pytest.mark.asyncio
async def test_beats_anchored_to_dialogue_lines():
    """一句对白一拍,beat_id 顺序编号,trigger=对白文本,dialogue_ref=speaker→target。"""
    stage = await _draft({})
    assert [b.beat_id for b in stage.beats] == ["bt001", "bt002", "bt003"]
    assert stage.beats[0].trigger == "求道长收留。"
    assert stage.beats[0].dialogue_ref == "王生→老道"
    assert stage.scene_ref == 3
    assert stage.assumed is True


@pytest.mark.asyncio
async def test_dialogue_sightlines_derived_deterministically():
    """INC-001 §H 升格:对白 speaker→target → 权威视线(assumed=False),即使 LLM 全空也在。"""
    stage = await _draft({})
    sl = {(s.at_beat, s.char_id, s.looking_at): s for s in stage.blocking.sightlines}
    assert sl[("bt001", "王生", "老道")].assumed is False
    assert sl[("bt002", "老道", "王生")].assumed is False
    assert sl[("bt003", "店家", "王生")].assumed is False


@pytest.mark.asyncio
async def test_sightline_dropped_when_target_absent_or_self():
    """target 不在场 / 指向自己 → 不成视线(与 tongjian_render 校验一致)。"""
    scene = ScreenplayScene(
        scene_no=1,
        characters_present=["甲", "乙"],
        dialogue=[
            ScreenplayDialogueLine(character_name="甲", text="独白。", target_name="甲"),  # 指自己
            ScreenplayDialogueLine(
                character_name="乙", text="对空。", target_name="丙"
            ),  # 丙不在场
        ],
    )

    async def _fake(_llm, _prompt):
        return {}

    with patch("hevi.director.scene_stage._call_llm_json", side_effect=_fake):
        stage = await generate_scene_stage_draft(scene=scene, design_list=_design(), llm=object())
    assert stage.blocking.sightlines == []  # 两条都不合法


@pytest.mark.asyncio
async def test_fallback_axis_and_attention_when_llm_empty():
    """LLM 全空 → 主轴取前两名在场角色、每拍焦点默认落说话人。"""
    stage = await _draft({})
    assert stage.axis.primary_axis == ["王生", "老道"]
    assert "画左" in stage.axis.side_convention
    assert [a.focus_target for a in stage.attention_script] == ["王生", "老道", "店家"]
    assert all(a.reason == "speaking" for a in stage.attention_script)
    # 兜底落位:每个在场角色一条
    assert {p.char_id for p in stage.blocking.initial_positions} == {"王生", "老道", "店家"}


@pytest.mark.asyncio
async def test_llm_draft_parsed_and_out_of_scope_refs_filtered():
    """LLM 草案的 space_map/blocking/axis/coverage 被解析;越界引用(未在场角色/未知 beat)被丢。"""
    stage = await _draft(
        {
            "space_map": {
                "zones": [{"zone_id": "z1", "name": "门口", "rel_position": "左"}],
                "landmarks": [
                    {"name": "油灯", "zone_id": "z1"},
                    {"name": "不存在道具", "zone_id": "z1"},
                ],
            },
            "blocking": {
                "initial_positions": [
                    {"char_id": "王生", "zone_id": "z1", "facing": "面向老道", "posture": "站立"},
                    {"char_id": "路人甲", "zone_id": "z1"},  # 未在场 → 丢
                ],
                "sightlines": [{"at_beat": "bt002", "char_id": "店家", "looking_at": "油灯"}],
            },
            "axis": {"primary_axis": ["王生", "老道"], "side_convention": "王生画左"},
            "attention_script": [
                {
                    "at_beat": "bt001",
                    "focus_target": "老道",
                    "reason": "reacting",
                    "transition": "push",
                    "intensity": "exclusive",
                },
                {"at_beat": "zzz", "focus_target": "王生"},  # 未知 beat → 丢
            ],
            "coverage_plan": {
                "master": {
                    "setup_id": "master",
                    "axis_side": "left",
                    "shot_size": "全景",
                    "serves_beats": ["bt001", "bt002", "bt003"],
                    "subjects": ["王生", "老道"],
                },
                "setups": [
                    {
                        "setup_id": "s1",
                        "axis_side": "left",
                        "shot_size": "中景",
                        "serves_beats": ["bt001", "zzz"],
                        "subjects": ["王生", "路人甲"],
                    },
                    {"axis_side": "right"},  # 无 setup_id → 丢
                ],
            },
        }
    )
    # space_map
    assert [z.zone_id for z in stage.space_map.zones] == ["z1"]
    assert [lm.name for lm in stage.space_map.landmarks] == ["油灯"]  # 未知道具被丢
    # blocking:未在场角色被丢;LLM 补的视线 assumed=True
    assert {p.char_id for p in stage.blocking.initial_positions} == {"王生"}
    llm_sl = [s for s in stage.blocking.sightlines if s.assumed]
    assert any(s.char_id == "店家" and s.looking_at == "油灯" for s in llm_sl)
    # attention:push/exclusive 保留;未知 beat 丢
    assert len(stage.attention_script) == 1
    assert stage.attention_script[0].transition == "push"
    assert stage.attention_script[0].intensity == "exclusive"
    # coverage:未知 beat_id / 未在场 subject 从列表过滤;无 setup_id 的整条丢
    assert stage.coverage_plan.master is not None
    assert [s.setup_id for s in stage.coverage_plan.setups] == ["s1"]
    assert stage.coverage_plan.setups[0].serves_beats == ["bt001"]  # zzz 被过滤
    assert stage.coverage_plan.setups[0].subjects == ["王生"]  # 路人甲被过滤


@pytest.mark.asyncio
async def test_angles_parsed_from_llm_draft():
    """SPEC-004 v2:LLM 给的 facing_deg/azimuth_deg 解析并归一到 0-359;非数→None。"""
    stage = await _draft(
        {
            "blocking": {
                "initial_positions": [
                    {"char_id": "王生", "facing_deg": 90},
                    {"char_id": "老道", "facing_deg": "270"},
                    {"char_id": "店家", "facing_deg": 450},  # 归一到 90
                ]
            },
            "coverage_plan": {
                "setups": [
                    {
                        "setup_id": "s1",
                        "azimuth_deg": 0,
                        "serves_beats": ["bt001"],
                        "subjects": ["王生"],
                    },
                    {
                        "setup_id": "s2",
                        "azimuth_deg": "bad",
                        "serves_beats": ["bt002"],
                        "subjects": ["老道"],
                    },
                ]
            },
        }
    )
    deg = {p.char_id: p.facing_deg for p in stage.blocking.initial_positions}
    assert deg == {"王生": 90, "老道": 270, "店家": 90}
    az = {c.setup_id: c.azimuth_deg for c in stage.coverage_plan.setups}
    assert az == {"s1": 0, "s2": None}  # 非数 → None


@pytest.mark.asyncio
async def test_invalid_transition_and_intensity_default():
    """非法 transition/intensity → 回落 cut/primary。"""
    stage = await _draft(
        {
            "attention_script": [
                {
                    "at_beat": "bt001",
                    "focus_target": "王生",
                    "transition": "zoom",
                    "intensity": "loud",
                }
            ]
        }
    )
    assert stage.attention_script[0].transition == "cut"
    assert stage.attention_script[0].intensity == "primary"


# ── 阶段 3:分镜 ↔ 场事实确定性链接 ──────────────────────────────────────────


def _shot(
    shot_id: str, scene_no: int, dlg: list[tuple[str, str]], chars: list[str]
) -> ShotListItem:
    return ShotListItem(
        shot_id=shot_id,
        scene_no=scene_no,
        dialogue_lines=[ShotListDialogueLine(character_name=s, text=t) for s, t in dlg],
        character_names=chars,
    )


@pytest.mark.asyncio
async def test_link_fills_refs_from_dialogue_beat_match():
    """镜头对白 → 精确匹配对白锚定的 beats,填 scene_stage_ref/beat_range/attention_ref。"""
    stage = await _draft({})  # scene_no=3,beats bt001(王生)/bt002(老道)/bt003(店家)
    shots = ShotList(
        shots=[
            _shot("SH1", 3, [("王生", "求道长收留。")], ["王生"]),  # → bt001
            _shot("SH2", 3, [("老道", "你受不得苦。"), ("店家", "客官莫强求。")], ["老道", "店家"]),
        ]
    )
    linked = link_shots_to_scene_stage(shots, SceneStageSet(stages=[stage]))
    assert linked.shots[0].scene_stage_ref == 3
    assert linked.shots[0].beat_range == ["bt001"]
    assert linked.shots[0].attention_ref == "bt001"  # 该拍有 attention 条目(兜底 speaking)
    assert linked.shots[1].beat_range == ["bt002", "bt003"]
    assert linked.shots[1].attention_ref == "bt002"  # beat_range 里第一个有 attention 的


@pytest.mark.asyncio
async def test_link_leaves_shot_without_matching_stage_untouched():
    """镜头 scene_no 无对应 SceneStage → 引用保持空(向后兼容旧 work)。"""
    stage = await _draft({})  # scene_no=3
    shots = ShotList(shots=[_shot("SH1", 99, [("某人", "台词")], ["某人"])])
    linked = link_shots_to_scene_stage(shots, SceneStageSet(stages=[stage]))
    assert linked.shots[0].scene_stage_ref is None
    assert linked.shots[0].beat_range == []


def test_pick_camera_setup_prefers_beat_and_subject_overlap():
    """择优机位:serves_beats 覆盖本镜 beats 优先,同分偏好 subjects 重叠多的。"""
    stage = SceneStage(
        scene_ref=1,
        coverage_plan=CoveragePlan(
            setups=[
                CameraSetup(setup_id="wide", serves_beats=["bt001", "bt002"], subjects=["甲"]),
                CameraSetup(setup_id="cu_乙", serves_beats=["bt002"], subjects=["乙"]),
            ]
        ),
    )
    shots = ShotList(
        shots=[
            _shot("SH1", 1, [], ["乙"]),  # 无对白 → beat_range 空 → 退回第一个 setup
        ]
    )
    # 直接给一个已知 beat_range 的镜头(手工设,绕过对白匹配)测择优
    shot = ShotListItem(shot_id="SH2", scene_no=1, character_names=["乙"], beat_range=["bt002"])
    from hevi.director.scene_stage import _pick_camera_setup

    # bt002 被两个机位覆盖,乙 subject 命中 cu_乙 → 择 cu_乙
    assert _pick_camera_setup(shot, stage, ["bt002"]) == "cu_乙"
    # 无覆盖(bt999)→ 退回第一个 setup
    assert _pick_camera_setup(shot, stage, ["bt999"]) == "wide"
    # 走链接:SH1 无对白 beat_range 空 → 退回第一个 setup
    linked = link_shots_to_scene_stage(shots, SceneStageSet(stages=[stage]))
    assert linked.shots[0].camera_setup_ref == "wide"


def test_project_shot_space_composes_blocking_focus_and_screen():
    """§3.2 确定性投影:落位/朝向 + 焦点(带 intensity)+ 画面正方向,全从 SceneStage 派生。"""
    from hevi.director.pipeline_schemas import (
        AttentionBeat,
        InitialPosition,
        SceneAxis,
        SceneBlocking,
        SceneSpaceMap,
        SceneZone,
    )
    from hevi.director.scene_stage import project_shot_space

    stage = SceneStage(
        scene_ref=1,
        space_map=SceneSpaceMap(
            zones=[SceneZone(zone_id="z1", name="门口"), SceneZone(zone_id="z2", name="窗边")]
        ),
        blocking=SceneBlocking(
            initial_positions=[
                InitialPosition(char_id="王生", zone_id="z1", facing="面向老道"),
                InitialPosition(char_id="老道", zone_id="z2", facing="背对窗"),
            ]
        ),
        axis=SceneAxis(primary_axis=["王生", "老道"], side_convention="王生画左,老道画右"),
        attention_script=[
            AttentionBeat(at_beat="bt001", focus_target="老道", intensity="exclusive")
        ],
    )
    shot = ShotListItem(
        shot_id="SH1",
        scene_no=1,
        character_names=["王生", "老道"],
        scene_stage_ref=1,
        beat_range=["bt001"],
        attention_ref="bt001",
    )
    text = project_shot_space(stage, shot)
    assert "王生在门口、面向老道" in text
    assert "老道在窗边、背对窗" in text
    assert "焦点在老道(独占前景、浅景深虚化他人)" in text  # intensity=exclusive → 虚化他人
    assert "王生画左,老道画右" in text  # 画面正方向(轴线约定)


def test_project_shot_space_uses_moved_zone_within_beat_range():
    """beat_range 内发生的移动 → 用移动后的落位(动线),而非初始位置。"""
    from hevi.director.pipeline_schemas import (
        BlockingMove,
        InitialPosition,
        SceneBlocking,
        SceneSpaceMap,
        SceneZone,
    )
    from hevi.director.scene_stage import project_shot_space

    stage = SceneStage(
        scene_ref=1,
        space_map=SceneSpaceMap(
            zones=[SceneZone(zone_id="z1", name="门口"), SceneZone(zone_id="z2", name="桌旁")]
        ),
        blocking=SceneBlocking(
            initial_positions=[InitialPosition(char_id="王生", zone_id="z1")],
            moves=[BlockingMove(char_id="王生", at_beat="bt002", from_zone="z1", to_zone="z2")],
        ),
    )
    shot = ShotListItem(shot_id="SH1", scene_no=1, character_names=["王生"], beat_range=["bt002"])
    assert "王生在桌旁" in project_shot_space(stage, shot)  # 移动后
    shot_before = ShotListItem(
        shot_id="SH0", scene_no=1, character_names=["王生"], beat_range=["bt001"]
    )
    assert "王生在门口" in project_shot_space(stage, shot_before)  # 未移动


# ── SPEC-004 v2:几何选 Subject3D 视图 ──────────────────────────────────────


def test_resolve_subject_view_cardinal_deltas():
    """相机方位角 − 角色朝向,量化到 front/right/back/left。"""
    from hevi.director.scene_stage import resolve_subject_view

    # 角色朝向 0°:相机在 0°(角色正对相机)→ front;180°(背对)→ back
    assert resolve_subject_view(0, 0) == "front"
    assert resolve_subject_view(180, 0) == "back"
    assert resolve_subject_view(90, 0) == "right"
    assert resolve_subject_view(270, 0) == "left"
    # 相对量:角色朝 90°、相机在 90° → 仍是 front(相机在角色正对方向)
    assert resolve_subject_view(90, 90) == "front"
    assert resolve_subject_view(180, 90) == "right"


def test_resolve_subject_view_quantizes_and_wraps():
    """非整 90° → 量化到最近;负/超界 → 取模。"""
    from hevi.director.scene_stage import resolve_subject_view

    assert resolve_subject_view(100, 0) == "right"  # 100→90
    assert resolve_subject_view(44, 0) == "front"  # 44→0
    assert resolve_subject_view(46, 0) == "right"  # 46→90
    assert resolve_subject_view(-90, 0) == "left"  # -90 ≡ 270


def test_resolve_subject_view_missing_angle_falls_back_to_front():
    """任一角度缺失 → front(退回 2D 真照)。"""
    from hevi.director.scene_stage import resolve_subject_view

    assert resolve_subject_view(None, 0) == "front"
    assert resolve_subject_view(90, None) == "front"
    assert resolve_subject_view(None, None) == "front"


def test_compute_shot_views_from_geometry():
    """每镜每角色的视图 = resolve_subject_view(该镜机位 azimuth, 该角色 facing_deg)。"""
    from hevi.director.pipeline_schemas import (
        CameraSetup,
        CoveragePlan,
        InitialPosition,
        SceneBlocking,
    )
    from hevi.director.scene_stage import compute_shot_views

    stage = SceneStage(
        scene_ref=1,
        blocking=SceneBlocking(
            initial_positions=[
                InitialPosition(char_id="甲", facing_deg=0),
                InitialPosition(char_id="乙", facing_deg=180),
            ]
        ),
        coverage_plan=CoveragePlan(setups=[CameraSetup(setup_id="s1", azimuth_deg=90)]),
    )
    shots = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH1",
                scene_no=1,
                scene_stage_ref=1,
                camera_setup_ref="s1",
                character_names=["甲", "乙"],
            ),
            ShotListItem(shot_id="SH2", scene_no=99, character_names=["甲"]),  # 无场事实 → 不产条目
        ]
    )
    views = compute_shot_views(shots, SceneStageSet(stages=[stage]))
    # 机位 azimuth=90:甲 facing 0 → delta 90 → right;乙 facing 180 → delta -90≡270 → left
    assert views["SH1"] == {"甲": "right", "乙": "left"}
    assert "SH2" not in views  # 未接场事实的镜头不产条目


def test_compute_shot_views_missing_azimuth_falls_back_front():
    """机位无 azimuth_deg → 该镜所有角色 front(渲染层退回 2D 真照)。"""
    from hevi.director.pipeline_schemas import (
        CameraSetup,
        CoveragePlan,
        InitialPosition,
        SceneBlocking,
    )
    from hevi.director.scene_stage import compute_shot_views

    stage = SceneStage(
        scene_ref=1,
        blocking=SceneBlocking(initial_positions=[InitialPosition(char_id="甲", facing_deg=90)]),
        coverage_plan=CoveragePlan(setups=[CameraSetup(setup_id="s1")]),  # azimuth_deg=None
    )
    shots = ShotList(
        shots=[
            ShotListItem(
                shot_id="SH1",
                scene_no=1,
                scene_stage_ref=1,
                camera_setup_ref="s1",
                character_names=["甲"],
            )
        ]
    )
    assert compute_shot_views(shots, SceneStageSet(stages=[stage]))["SH1"] == {"甲": "front"}
