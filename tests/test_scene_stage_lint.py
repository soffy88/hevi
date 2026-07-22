"""SPEC-004 §4 六条确定性 lint 测试(L1 跳轴 / L2 反打差异 / L3 eyeline / L4 剪辑冗余 /
L5 落位契约 / L6 对话戏 coverage 配比)。"""

from __future__ import annotations

from hevi.director.pipeline_schemas import (
    AxisShift,
    CameraSetup,
    CoveragePlan,
    SceneAxis,
    SceneBlocking,
    SceneStage,
    SceneStageSet,
    ShotBlocking,
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


def _shot(
    sid,
    *,
    setup="",
    size="",
    beats=None,
    attn="",
    dlg=None,
    blocking=None,
    shot_type="",
    chars=None,
) -> ShotListItem:
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
        blocking=blocking or [],
        shot_type=shot_type,
        character_names=chars or [],
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


def test_l5_blocking_conflicts_with_side_convention_flagged():
    """2026-07-18 真机复验撞见的真实场景复现:blocking 文本写"老道士:画面左侧"，
    直接矛盾 side_convention"王生恒在画左,老道士恒在画右"→ L5。"""
    stage = _stage(axis=SceneAxis(side_convention="王生恒在画左，老道士恒在画右"))
    sl = ShotList(
        shots=[
            _shot(
                "SH1",
                setup="s_left",
                beats=["bt001"],
                blocking=[
                    ShotBlocking(character_name="老道士", position="画面左侧"),
                    ShotBlocking(character_name="王生", position="画面右侧"),
                ],
            )
        ]
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l5 = [f for f in findings if f.rule == "L5"]
    assert len(l5) == 2  # 两个角色都写反了
    assert any("老道士" in f.message for f in l5)
    assert any("王生" in f.message for f in l5)


def test_l5_blocking_consistent_with_side_convention_no_finding():
    """blocking 文本跟 side_convention 一致 → 不报 L5。"""
    stage = _stage(axis=SceneAxis(side_convention="王生恒在画左，老道士恒在画右"))
    sl = ShotList(
        shots=[
            _shot(
                "SH1",
                setup="s_left",
                beats=["bt001"],
                blocking=[
                    ShotBlocking(character_name="王生", position="画面左侧"),
                    ShotBlocking(character_name="老道士", position="画面右侧"),
                ],
            )
        ]
    )
    assert "L5" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l5_no_side_convention_no_finding():
    """SceneStage 没锁 side_convention(空串)→ 无从判矛盾,不报 L5。"""
    stage = _stage()  # side_convention 默认空串
    sl = ShotList(
        shots=[
            _shot(
                "SH1",
                setup="s_left",
                beats=["bt001"],
                blocking=[ShotBlocking(character_name="王生", position="画面右侧")],
            )
        ]
    )
    assert "L5" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l5_blocking_without_explicit_side_no_finding():
    """blocking 文本没写左右(如"居中而立")→ 无法判定,不报 L5(不是矛盾,是没信息)。"""
    stage = _stage(axis=SceneAxis(side_convention="王生恒在画左，老道士恒在画右"))
    sl = ShotList(
        shots=[
            _shot(
                "SH1",
                setup="s_left",
                beats=["bt001"],
                blocking=[ShotBlocking(character_name="王生", position="石阶中央，伏地")],
            )
        ]
    )
    assert "L5" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


# ── L6 对话戏 coverage 配比(INC-004 §1.3)────────────────────────────────────


def _dlg_scene(*shots) -> ShotList:
    return ShotList(shots=list(shots))


def test_l6a_opening_clean_single_flagged_as_error():
    """出场人物≥2 且含对白的场次,开场不是 master/two_shot → L6a,severity=error。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词", "老道士")]),
        _shot("SH2", shot_type="two_shot", chars=["王生", "老道士"]),
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l6a = [f for f in findings if f.rule == "L6a"]
    assert len(l6a) == 1
    assert l6a[0].severity == "error"
    assert l6a[0].shot_ids == ["SH1"]


def test_l6a_opening_master_no_finding():
    """开场是 master → 不报 L6a。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH2", shot_type="ots", chars=["王生", "老道士"], dlg=[("王生", "台词", "老道士")]),
    )
    assert "L6a" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l6b_too_many_clean_single_flagged():
    """clean_single 占比 > 40% → L6b。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH2", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词", "老道士")]),
        _shot("SH3", shot_type="clean_single", chars=["老道士"], dlg=[("老道士", "台词", "王生")]),
        _shot("SH4", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词", "老道士")]),
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l6b = [f for f in findings if f.rule == "L6b"]
    assert len(l6b) == 1
    assert "75%" in l6b[0].message or "占比" in l6b[0].message


def test_l6b_within_budget_no_finding():
    """clean_single 占比 ≤ 40% → 不报 L6b。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH2", shot_type="ots", chars=["王生", "老道士"], dlg=[("王生", "台词", "老道士")]),
        _shot("SH3", shot_type="ots", chars=["王生", "老道士"], dlg=[("老道士", "台词", "王生")]),
        _shot("SH4", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词", "老道士")]),
    )
    assert "L6b" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l6c_alternating_clean_single_different_speakers_flagged():
    """相邻两镜都是 clean_single 且说话人不同(单人轮播反打)→ L6c,建议改 ots。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH2", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词1", "老道士")]),
        _shot("SH3", shot_type="clean_single", chars=["老道士"], dlg=[("老道士", "台词2", "王生")]),
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l6c = [f for f in findings if f.rule == "L6c"]
    assert len(l6c) == 1
    assert l6c[0].shot_ids == ["SH2", "SH3"]
    assert "ots" in l6c[0].message


def test_l6c_same_speaker_consecutive_clean_single_no_finding():
    """相邻 clean_single 但说话人相同(同一人连续两镜,不是反打轮播)→ 不报 L6c。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH2", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词1", "老道士")]),
        _shot("SH3", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词2", "老道士")]),
    )
    assert "L6c" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l6d_five_consecutive_shots_without_relation_shot_flagged():
    """连续 5 镜没有 two_shot/master → L6d。"""
    stage = _stage()
    shots = [_shot("SH0", shot_type="master", chars=["王生", "老道士"])]
    for i in range(1, 6):
        shots.append(
            _shot(
                f"SH{i}",
                shot_type="clean_single",
                chars=["王生"],
                dlg=[("王生", f"台词{i}", "老道士")],
            )
        )
    sl = _dlg_scene(*shots)
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    l6d = [f for f in findings if f.rule == "L6d"]
    assert len(l6d) == 1
    assert l6d[0].shot_ids == [s.shot_id for s in shots[1:6]]


def test_l6d_relation_shot_within_window_no_finding():
    """5 镜内插入了一个 two_shot → 不报 L6d。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH0", shot_type="master", chars=["王生", "老道士"]),
        _shot("SH1", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词1", "老道士")]),
        _shot("SH2", shot_type="two_shot", chars=["王生", "老道士"]),
        _shot("SH3", shot_type="clean_single", chars=["老道士"], dlg=[("老道士", "台词2", "王生")]),
        _shot("SH4", shot_type="clean_single", chars=["王生"], dlg=[("王生", "台词3", "老道士")]),
        _shot("SH5", shot_type="clean_single", chars=["老道士"], dlg=[("老道士", "台词4", "王生")]),
    )
    assert "L6d" not in _rules(lint_scene_stage(sl, SceneStageSet(stages=[stage])))


def test_l6_skipped_when_single_character_scene():
    """单人场(出场人物 < 2)→ L6 全部跳过,即便全是 clean_single 也不报。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="clean_single", chars=["王生"], dlg=[("王生", "独白", "")]),
        _shot("SH2", shot_type="clean_single", chars=["王生"], dlg=[("王生", "独白2", "")]),
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    assert not any(f.rule.startswith("L6") for f in findings)


def test_l6_skipped_when_no_dialogue():
    """无对白的动作场(即便≥2人出场)→ L6 全部跳过,没有"对话戏"可言。"""
    stage = _stage()
    sl = _dlg_scene(
        _shot("SH1", shot_type="clean_single", chars=["王生"]),
        _shot("SH2", shot_type="clean_single", chars=["老道士"]),
    )
    findings = lint_scene_stage(sl, SceneStageSet(stages=[stage]))
    assert not any(f.rule.startswith("L6") for f in findings)
