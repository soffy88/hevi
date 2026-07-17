"""INC-002 第一批验收:15 秒五阶段镜头的时序提示词编译 + P1/P5 lint(零模型、纯确定性)。"""

from __future__ import annotations

from hevi.director.performance_track import (
    compile_temporal_prompt,
    lint_performance_track,
)
from hevi.director.pipeline_schemas import (
    EmotionalStateCurve,
    EyelineTrack,
    PerformanceBody,
    PerformancePhase,
    PerformanceTrack,
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
