"""INC-002 第一批验收:15 秒五阶段镜头的时序提示词编译 + P1/P5 lint(零模型、纯确定性)。"""

from __future__ import annotations

from hevi.director.performance_track import (
    beat_slices,
    camera_curve_match,
    compile_temporal_prompt,
    compile_temporal_prompt_at_tier,
    downsample_track,
    expected_handheld_trend,
    lint_performance_track,
    scale_preset_to_duration,
    tier_for_baseline,
)
from hevi.director.pipeline_schemas import (
    CameraBreathing,
    CameraCurve,
    CameraMovement,
    EmotionalStateCurve,
    EyelineTrack,
    FacialPerformance,
    FacialPhysiology,
    FocusCurve,
    HandheldCurve,
    MuscleAction,
    PerformanceBody,
    PerformancePhase,
    PerformancePreset,
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


# ── 第三批:CameraCurve(运镜曲线)+ P2/P4/P6 + camera_curve_match ──────────────


def _cam_phase(
    order,
    t0,
    t1,
    *,
    freq=(0.0, 0.0),
    enabled=True,
    strictness="soft",
    rack_to="",
    movement="static",
    breath_sync="none",
):
    return PerformancePhase(
        phase_id=f"ph{order}",
        order=order,
        t_start_s=t0,
        t_end_s=t1,
        label="运镜",
        camera_curve=CameraCurve(
            handheld=HandheldCurve(
                enabled=enabled,
                frequency_start=freq[0],
                frequency_end=freq[1],
                amplitude_start=0.2,
                amplitude_end=0.5,
                easing="accelerate",
            ),
            focus=FocusCurve(
                lock_target="女子双眼",
                lock_strictness=strictness,
                rack_to=rack_to,
                depth_of_field="shallow",
            ),
            movement=CameraMovement(type=movement, speed_start=0.1, speed_end=0.4),
            breathing=CameraBreathing(enabled=breath_sync != "none", sync_to=breath_sync),
        ),
    )


def test_camera_curve_compiles():
    """运镜曲线逐项编译:手持频率曲线 + 焦点锁死度 + 推拉 + 镜头呼吸(§4 独有项)。"""
    track = PerformanceTrack(
        total_duration_s=5.0,
        phases=[
            _cam_phase(
                1,
                0.0,
                5.0,
                freq=(0.2, 0.9),
                strictness="absolute",
                movement="push_in",
                breath_sync="character_breath",
            )
        ],
    )
    line = compile_temporal_prompt(track)
    assert "运镜:" in line
    assert "手持晃动 频率0.2→0.9" in line and "加速" in line
    assert "焦点死锁在女子双眼" in line
    assert "推近" in line
    assert "镜头呼吸感(与人物呼吸同步)" in line  # Hevi 独有高级项


def test_p2_absolute_focus_forbids_rack():
    """P2:focus absolute 死锁 + rack_to 并存 → 自相矛盾被拦。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[_cam_phase(1, 0.0, 3.0, strictness="absolute", rack_to="背景火光")],
    )
    assert any(f.rule == "P2" for f in lint_performance_track(track))


def test_p4_handheld_frequency_continuity():
    """P4:手持频率跨 phase 边界连续 → 过;突变 → 拦。"""
    ok = PerformanceTrack(
        total_duration_s=6.0,
        phases=[_cam_phase(1, 0.0, 3.0, freq=(0.2, 0.5)), _cam_phase(2, 3.0, 6.0, freq=(0.5, 0.8))],
    )
    assert [f for f in lint_performance_track(ok) if f.rule == "P4"] == []
    jump = PerformanceTrack(
        total_duration_s=6.0,
        phases=[_cam_phase(1, 0.0, 3.0, freq=(0.2, 0.5)), _cam_phase(2, 3.0, 6.0, freq=(0.9, 1.0))],
    )
    assert any(f.rule == "P4" and "突变" in f.message for f in lint_performance_track(jump))


def test_p6_conservation_facial_density_vs_motion():
    """P6:面部细节密度高 + 身体大幅运动(collapsing)并存 → 守恒律警告。"""
    dense_facial = FacialPerformance(
        muscle_actions=[
            MuscleAction(visible_result="眉头紧皱"),
            MuscleAction(visible_result="咬肌绷紧"),
        ],
        physiology=FacialPhysiology(
            tear_state="brimming",
            eye_vasculature="congested",
            blink="forced_open",
            swallow=True,
            lip_state="trembling",
        ),
    )
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="ph1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                facial_performance=dense_facial,
                body=PerformanceBody(tension="collapsing"),
            )
        ],
    )
    assert any(f.rule == "P6" and f.severity == "warn" for f in lint_performance_track(track))


def test_camera_curve_match_optical_flow_primitive():
    """camera_curve_match:合成运动幅度序列的趋势判定(确定性、零模型)。"""
    assert camera_curve_match([1, 2, 3, 4, 5, 6], "increasing")["match"] is True
    assert camera_curve_match([6, 5, 4, 3, 2, 1], "decreasing")["match"] is True
    assert camera_curve_match([5, 5, 5, 5, 5, 5], "flat")["match"] is True
    assert camera_curve_match([1, 2, 3, 4, 5, 6], "decreasing")["match"] is False
    assert camera_curve_match([1, 2], "increasing")["match"] is None  # 帧数不足


def test_expected_handheld_trend():
    """expected_handheld_trend:从 frequency_start→end 推期望趋势。"""
    assert (
        expected_handheld_trend(
            CameraCurve(
                handheld=HandheldCurve(enabled=True, frequency_start=0.2, frequency_end=0.8)
            )
        )
        == "increasing"
    )
    assert (
        expected_handheld_trend(
            CameraCurve(
                handheld=HandheldCurve(enabled=True, frequency_start=0.8, frequency_end=0.2)
            )
        )
        == "decreasing"
    )
    assert expected_handheld_trend(None) == "flat"


def test_camera_absent_is_inert():
    """未填 camera_curve → 无"运镜:"段(inert)。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="p1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                label="x",
                emotional_state=EmotionalStateCurve(primary="悲"),
            )
        ],
    )
    assert "运镜:" not in compile_temporal_prompt(track)


# ── 第四批:PerformancePreset 拉伸 + L0–L3 密度档降采样 ─────────────────────────


def _l3_phase(order, t0, t1):
    """一个 L3 满配 phase(eyeline+emotional+facial 含 muscle + camera)。"""
    return PerformancePhase(
        phase_id=f"ph{order}",
        order=order,
        t_start_s=t0,
        t_end_s=t1,
        label="满配",
        eyeline_track=EyelineTrack(state="breaking", direction="down"),
        emotional_state=EmotionalStateCurve(primary="崩溃", intensity=0.8),
        facial_performance=FacialPerformance(
            muscle_actions=[
                MuscleAction(
                    muscle="corrugator",
                    action="contract",
                    intensity=0.9,
                    visible_result="眉头痛苦紧皱",
                )
            ],
            physiology=FacialPhysiology(tear_state="brimming"),
        ),
        camera_curve=CameraCurve(
            handheld=HandheldCurve(enabled=True, frequency_start=0.3, frequency_end=0.8)
        ),
    )


def test_scale_preset_to_duration():
    """PerformancePreset 的相对时间(0–1)按时长拉伸成绝对秒。"""
    preset = PerformancePreset(
        preset_id="理智断裂五阶段",
        phases=[
            PerformancePhase(phase_id="a", order=1, t_start_s=0.0, t_end_s=0.4),
            PerformancePhase(phase_id="b", order=2, t_start_s=0.4, t_end_s=1.0),
        ],
    )
    track = scale_preset_to_duration(preset, 15.0)
    assert track.total_duration_s == 15.0
    assert track.phases[0].t_start_s == 0.0 and track.phases[0].t_end_s == 6.0
    assert track.phases[1].t_start_s == 6.0 and track.phases[1].t_end_s == 15.0
    # 拉伸后仍应通过 P1(时间窗无缝)
    assert [f for f in lint_performance_track(track) if f.rule == "P1"] == []


def test_tier_for_baseline():
    assert tier_for_baseline("economy") == "L0"
    assert tier_for_baseline("standard") == "L1"
    assert tier_for_baseline("cinematic") == "L2"
    assert tier_for_baseline("flagship") == "L3"
    assert tier_for_baseline("") == "L1"  # 默认


def test_downsample_tiers():
    """L0 丢整条;L1 丢 facial+camera;L2 丢 muscle 结构标注保 visible_result;L3 全保。"""
    track = PerformanceTrack(total_duration_s=6.0, phases=[_l3_phase(1, 0.0, 6.0)])

    assert downsample_track(track, "L0") is None

    l1 = downsample_track(track, "L1")
    assert l1.phases[0].facial_performance is None and l1.phases[0].camera_curve is None
    assert l1.phases[0].eyeline_track.state == "breaking"  # eyeline 保留

    l2 = downsample_track(track, "L2")
    assert l2.phases[0].facial_performance is not None  # facial 保留
    m = l2.phases[0].facial_performance.muscle_actions[0]
    assert m.visible_result == "眉头痛苦紧皱" and m.muscle == ""  # 结构标注被丢,visible_result 保

    l3 = downsample_track(track, "L3")
    assert l3.phases[0].facial_performance.muscle_actions[0].muscle == "corrugator"  # 全保

    # 原 track 不被就地改(downsample 返回拷贝)
    assert track.phases[0].facial_performance.muscle_actions[0].muscle == "corrugator"


def test_compile_at_tier_downsamples_without_error():
    """compile_temporal_prompt_at_tier:低档拿到高档 schema 也不报错(§5.4),只是内容变少。"""
    track = PerformanceTrack(total_duration_s=6.0, phases=[_l3_phase(1, 0.0, 6.0)])
    assert compile_temporal_prompt_at_tier(track, "L0") == ""  # 只剩 action_beats
    l1 = compile_temporal_prompt_at_tier(track, "L1")
    assert "面部:" not in l1 and "运镜:" not in l1 and "视线开始游离" in l1
    l2 = compile_temporal_prompt_at_tier(track, "L2")
    assert "面部:" in l2 and "运镜:" in l2 and "眉头痛苦紧皱" in l2


# ── render 消费:§1.1 phase→beat 时刻切片 ──────────────────────────────────────


def test_beat_slices_maps_first_peak_aftermath():
    """表演时间轴按 首(t=0)/关键(中点)/尾(末)三时刻切片,映射到对应关键帧。"""
    slices = beat_slices(_five_phase_15s())
    assert "视线锁定" in slices["first"]  # t=0 → 理智克制/locked
    assert "视线回避移开" in slices["peak"]  # t=7.5 → averted 段
    assert "双眼闭合" in slices["aftermath"]  # t=15 → closed 段
    assert "[" not in slices["first"]  # 注入关键帧用,无时间窗头


def test_beat_slices_excludes_camera_for_stills():
    """静帧渲不出运镜 → beat_slices 不含运镜(只面部/视线/情绪/身体)。"""
    track = PerformanceTrack(
        total_duration_s=4.0, phases=[_cam_phase(1, 0.0, 4.0, freq=(0.2, 0.9))]
    )
    s = beat_slices(track)
    assert "运镜:" not in s["first"] and "手持" not in s["first"]


def test_beat_slices_empty_inert():
    assert beat_slices(None) == {}
    assert beat_slices(PerformanceTrack()) == {}
