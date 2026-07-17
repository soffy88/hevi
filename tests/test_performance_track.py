"""INC-002 第一批验收:15 秒五阶段镜头的时序提示词编译 + P1/P5 lint(零模型、纯确定性)。"""

from __future__ import annotations

from hevi.director.performance_track import (
    compile_temporal_prompt,
    lint_performance_track,
)
from hevi.director.pipeline_schemas import (
    EmotionalStateCurve,
    EyelineTrack,
    FacialPerformance,
    FacialPhysiology,
    MuscleAction,
    PerformanceBody,
    PerformancePhase,
    PerformanceTrack,
    Pupil,
    SkinTexture,
    TearDetail,
)


def _phase(
    order, t0, t1, label, state, direction="center", speed="slow", primary="", intensity=0.0
):
    return PerformancePhase(
        phase_id=f"ph{order}",
        order=order,
        t_start_s=t0,
        t_end_s=t1,
        label=label,
        eyeline_track=EyelineTrack(state=state, direction=direction, transition_speed=speed),
        emotional_state=EmotionalStateCurve(primary=primary, intensity=intensity),
        body=PerformanceBody(tension="taut", breath="held"),
    )


def _five_phase_15s() -> PerformanceTrack:
    """一个合法的 15 秒五阶段情绪弧(理智→断裂→回避→回视→闭眼),时间窗无缝、视线相邻演化。"""
    return PerformanceTrack(
        total_duration_s=15.0,
        phases=[
            _phase(1, 0.0, 3.0, "理智克制", "locked", "center", primary="强忍", intensity=0.4),
            _phase(2, 3.0, 6.5, "理智断裂", "breaking", "down", "quick", "崩溃", 0.7),
            _phase(
                3, 6.5, 10.0, "向下退缩回避", "averted", "down_left", primary="羞愤", intensity=0.85
            ),
            _phase(4, 10.0, 13.0, "重新抬眼回视", "returning", "center", "trembling", "决绝", 0.9),
            _phase(5, 13.0, 15.0, "阖眼", "closed", "center", primary="万念俱灰", intensity=1.0),
        ],
    )


def test_compile_temporal_prompt_five_phases():
    """时序提示词逐段正确:5 段各一行,时间窗 + 标签 + 视线/情绪/身体都编进去。"""
    out = compile_temporal_prompt(_five_phase_15s())
    lines = out.splitlines()
    assert len(lines) == 5
    assert lines[0].startswith("[0–3s] 理智克制 → ")
    assert "视线锁定" in lines[0]
    assert "情绪:强忍(强度0.4)" in lines[0]
    # 第二段:视线开始游离、朝下、quick
    assert lines[1].startswith("[3–6.5s] 理智断裂 → ")
    assert "视线开始游离" in lines[1] and "朝下方" in lines[1] and "快速" in lines[1]
    # 闭眼段:不带方向(闭眼无朝向)
    assert lines[4].startswith("[13–15s] 阖眼 → ")
    assert "双眼闭合" in lines[4] and "朝正前方" not in lines[4]


def test_valid_track_lints_clean():
    """合法 15 秒五阶段 → P1/P5 全过,零 finding(时间窗无缝、视线相邻演化)。"""
    assert lint_performance_track(_five_phase_15s(), shot_id="SH001") == []


def test_p1_catches_gap_overlap_and_total_mismatch():
    """P1:时间轴缝隙 + 末段≠total 都被拦。"""
    t = _five_phase_15s()
    t.phases[2].t_start_s = 7.0  # 与 phase2 的 6.5 之间留 0.5s 缝隙
    findings = lint_performance_track(t, shot_id="SH001")
    rules = {f.rule for f in findings}
    assert "P1" in rules
    assert any("缝隙" in f.message for f in findings)


def test_p1_catches_total_duration_mismatch():
    """P1:末段结束 ≠ total_duration_s。"""
    t = _five_phase_15s()
    t.total_duration_s = 20.0  # 末段仍 15s
    findings = lint_performance_track(t, shot_id="SH001")
    assert any(f.rule == "P1" and "total_duration_s" in f.message for f in findings)


def test_p5_catches_illegal_eyeline_jump():
    """P5:locked→averted 跳过 breaking,且非 snap → 拦。"""
    t = _five_phase_15s()
    t.phases[1].eyeline_track.state = "averted"  # phase1 locked → phase2 averted(跳变)
    t.phases[1].eyeline_track.transition_speed = "slow"
    findings = lint_performance_track(t, shot_id="SH001")
    assert any(f.rule == "P5" and "locked→averted" in f.message for f in findings)


def test_p5_allows_jump_when_snap():
    """P5:同样的跳变,transition_speed=snap → 放行(骤然瞬移是合法表演)。"""
    t = _five_phase_15s()
    t.phases[1].eyeline_track.state = "averted"
    t.phases[1].eyeline_track.transition_speed = "snap"
    assert [f for f in lint_performance_track(t) if f.rule == "P5"] == []


def test_empty_track_is_inert():
    """未填 performance_track → 编译空串、零 finding(向后兼容 inert)。"""
    assert compile_temporal_prompt(None) == ""
    assert compile_temporal_prompt(PerformanceTrack()) == ""
    assert lint_performance_track(None) == []


# ── 第二批:FacialPerformance(面部生理层)──────────────────────────────────


def _facial_phase(order, t0, t1, tear, *, muscle_visible="", skin=False):
    fp = FacialPerformance(
        muscle_actions=(
            [
                MuscleAction(
                    muscle="corrugator",
                    action="contract",
                    intensity=0.8,
                    visible_result=muscle_visible,
                )
            ]
            if muscle_visible
            else []
        ),
        physiology=FacialPhysiology(
            tear_state=tear,
            tear_detail=TearDetail(side="right"),
            eye_vasculature="congested",
            pupil=Pupil(dilation=0.6, movement="微微震颤"),
            blink="forced_open",
            swallow=True,
            swallow_difficulty="艰难",
            lip_state="trembling",
            skin_flush="cheeks",
        ),
        skin_texture=(
            SkinTexture(
                quality="natural_imperfect",
                pores="visible",
                blemishes=["左颊一道战损擦痕"],
                sweat="beads",
                preserve_base_tone=True,
            )
            if skin
            else SkinTexture()
        ),
    )
    return PerformancePhase(
        phase_id=f"ph{order}",
        order=order,
        t_start_s=t0,
        t_end_s=t1,
        label="面部",
        facial_performance=fp,
    )


def test_facial_physiology_compiles():
    """面部生理逐项编译进时序提示词(泪/血管/瞳孔/眨眼/吞咽/唇/潮红)。"""
    track = PerformanceTrack(
        total_duration_s=3.0, phases=[_facial_phase(1, 0.0, 3.0, "brimming", skin=True)]
    )
    line = compile_temporal_prompt(track)
    assert "面部:" in line
    assert "右眼泪水将溢未溢" in line  # tear_state + tear_detail.side
    assert "眼白充血泛红" in line and "瞳孔放大0.6" in line and "强撑着睁大不闭" in line
    assert "艰难吞咽,喉结滚动" in line and "嘴唇颤抖" in line and "双颊泛红" in line
    # 肤质肌理进 prompt(第二批验收)
    assert (
        "自然微瑕的真实肤质" in line
        and "左颊一道战损擦痕" in line
        and "保留原本面部底色不掩盖" in line
    )


def test_muscle_action_compiles_visible_result_not_anatomy():
    """muscle_actions 编译输出 visible_result,绝不输出解剖学名词(§6 编译纪律)。"""
    track = PerformanceTrack(
        total_duration_s=2.0,
        phases=[_facial_phase(1, 0.0, 2.0, "none", muscle_visible="眉头痛苦紧皱")],
    )
    line = compile_temporal_prompt(track)
    assert "眉头痛苦紧皱" in line
    assert "corrugator" not in line and "降眉肌" not in line


def test_p3_tear_evolution_clean_and_violations():
    """P3:泪水单调演化(welling→film→brimming)过;倒流/跳跃被拦。"""
    ok = PerformanceTrack(
        total_duration_s=9.0,
        phases=[
            _facial_phase(1, 0.0, 3.0, "welling"),
            _facial_phase(2, 3.0, 6.0, "film"),
            _facial_phase(3, 6.0, 9.0, "brimming"),
        ],
    )
    assert [f for f in lint_performance_track(ok) if f.rule == "P3"] == []

    backflow = PerformanceTrack(
        total_duration_s=6.0,
        phases=[_facial_phase(1, 0.0, 3.0, "falling"), _facial_phase(2, 3.0, 6.0, "welling")],
    )
    assert any(f.rule == "P3" and "倒流" in f.message for f in lint_performance_track(backflow))

    jump = PerformanceTrack(
        total_duration_s=6.0,
        phases=[_facial_phase(1, 0.0, 3.0, "none"), _facial_phase(2, 3.0, 6.0, "brimming")],
    )
    assert any(f.rule == "P3" and "跳跃" in f.message for f in lint_performance_track(jump))


def test_facial_absent_is_inert():
    """未填 facial_performance → 时序提示词无"面部:"段(降级为 emotional_state,inert)。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="ph1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                label="x",
                emotional_state=EmotionalStateCurve(primary="悲"),
            ),
        ],
    )
    assert "面部:" not in compile_temporal_prompt(track)
