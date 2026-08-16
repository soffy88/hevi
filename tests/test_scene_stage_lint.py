"""SPEC-004 §4 四条确定性 lint 测试(L1 跳轴 / L2 反打差异 / L3 eyeline / L4 剪辑冗余)。"""

from __future__ import annotations

from hevi.director.pipeline_schemas import (
    AxisShift,
    CameraSetup,
    CoveragePlan,
    SceneAxis,
    SceneBlocking,
    SceneStage,
    SceneStageSet,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
    Sightline,
)
from hevi.director.scene_stage_lint import lint_scene_stage


def _stage(**kw) -> SceneStage:
    base: dict = {
        "scene_ref": 1,
        "coverage_plan": CoveragePlan(
            setups=[
                CameraSetup(setup_id="s_left", axis_side="left", shot_size="全景"),
                CameraSetup(setup_id="s_right", axis_side="right", shot_size="特写"),
            ]
        ),
    }
    base.update(kw)
    return SceneStage(**base)


def _shot(sid, *, setup="", size="", beats=None, attn="", dlg=None) -> ShotListItem:
    return ShotListItem(
        shot_id=sid,
        scene_no=1,
        scene_stage_ref=1,
        camera_setup_ref=setup,
        shot_size=size,
        beat_range=beats or [],
        attention_ref=attn,
        dialogue_lines=[
            ShotListDialogueLine(character_name=s, text=t, target_name=tg)
            for s, t, tg in (dlg or [])
        ],
    )


def _rules(findings) -> set[str]:
    return {f.rule for f in findings}


def test_l1_axis_jump_flagged_without_shift():
    """相邻镜头跨轴换侧(left→right)且无 axis_shift → L1。"""
    stage = _stage()
    sl = ShotList(
        shots=[
            _shot("SH1", setup="s_left", beats=["bt001"]),
            _shot("SH2", setup="s_right", beats=["bt002"]),  # 换到右侧,无 shift
        ]
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    assert "L1" in _rules(findings)
    assert findings[0].shot_ids == ["SH1", "SH2"]


def test_l1_axis_jump_allowed_with_declared_shift():
    """该拍有已声明 axis_shift → 合法转轴,不报 L1。"""
    stage = _stage(
        axis=SceneAxis(primary_axis=["甲", "乙"], axis_shifts=[AxisShift(at_beat="bt002")])
    )
    sl = ShotList(
        shots=[
            _shot("SH1", setup="s_left", beats=["bt001"]),
            _shot("SH2", setup="s_right", beats=["bt002"]),  # bt002 有 shift
        ]
    )
    assert "L1" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l1_same_side_no_finding():
    """同侧机位不报 L1。"""
    stage = _stage()
    sl = ShotList(
        shots=[
            _shot("SH1", setup="s_left", beats=["bt001"]),
            _shot("SH2", setup="s_left", beats=["bt002"]),
        ]
    )
    assert "L1" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l2_reverse_shot_size_too_close():
    """反打(焦点不同)但景别差 < 2 档(中↔近)→ L2。"""
    stage = _stage()
    sl = ShotList(
        shots=[
            _shot("SH1", setup="s_left", size="中景", beats=["bt001"], attn="bt001"),
            _shot(
                "SH2", setup="s_left", size="近景", beats=["bt002"], attn="bt002"
            ),  # 焦点不同=反打
        ]
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    assert "L2" in _rules(findings)


def test_l2_reverse_shot_size_ok_when_two_ranks_apart():
    """反打景别差 ≥ 2 档(全↔特写)→ 不报 L2。"""
    stage = _stage()
    sl = ShotList(
        shots=[
            _shot("SH1", size="全景", beats=["bt001"], attn="bt001", setup="s_left"),
            _shot("SH2", size="特写", beats=["bt002"], attn="bt002", setup="s_left"),
        ]
    )
    assert "L2" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l3_eyeline_mismatch_flagged():
    """镜头对白说给「乙」,但场事实该拍视线看向「丙」→ L3。"""
    stage = _stage(
        blocking=SceneBlocking(
            sightlines=[Sightline(at_beat="bt001", char_id="甲", looking_at="丙")]
        )
    )
    sl = ShotList(shots=[_shot("SH1", beats=["bt001"], setup="s_left", dlg=[("甲", "台词", "乙")])])
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    assert "L3" in _rules(findings)
    assert "乙" in findings[0].message and "丙" in findings[0].message


def test_l3_eyeline_consistent_no_finding():
    """对白 target 与场事实视线一致 → 不报 L3。"""
    stage = _stage(
        blocking=SceneBlocking(
            sightlines=[Sightline(at_beat="bt001", char_id="甲", looking_at="乙")]
        )
    )
    sl = ShotList(shots=[_shot("SH1", beats=["bt001"], setup="s_left", dlg=[("甲", "台词", "乙")])])
    assert "L3" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l4_beat_covered_by_single_setup_flagged():
    """某 beat 只被 1 个机位覆盖 → L4(无剪辑余地)。"""
    stage = _stage()
    sl = ShotList(
        shots=[
            _shot("SH1", setup="s_left", beats=["bt001", "bt002"]),
            _shot("SH2", setup="s_right", beats=["bt001"]),  # bt001 有 2 机位,bt002 只有 1
        ]
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l4 = [f for f in findings if f.rule == "L4"]
    assert len(l4) == 1
    assert "bt002" in l4[0].message


def test_unlinked_shots_skipped():
    """未接场事实(scene_stage_ref=None)的镜头整体跳过,不产生任何 finding。"""
    sl = ShotList(shots=[ShotListItem(shot_id="SH1", scene_no=1, camera_setup_ref="s_right")])
    assert lint_scene_stage(sl, SceneStageSet(stages=[_stage()])) == []
