"""INC-002 v0.2 第三批半验收:道具状态机 / 声音自动派生+咬合 / 光遮挡派生 / 负面派生。零模型。"""

from __future__ import annotations

from hevi.director.performance_derive import (
    compile_audio_prompt,
    derive_audio_track,
    derive_negatives,
    derive_occlusion,
    derive_sounds_for_phase,
    lint_audio_sync,
)
from hevi.director.performance_track import compile_temporal_prompt, lint_performance_track
from hevi.director.pipeline_schemas import (
    AudioTrack,
    FacialPerformance,
    FacialPhysiology,
    LightingKeyRatio,
    LightingOcclusion,
    LightingResponse,
    PerformanceBody,
    PerformancePhase,
    PerformanceTrack,
    PropContactState,
    PropPerformance,
    PropTremor,
    ShotListItem,
)


def _firearm_phase(order, t0, t1, state, transition_from, *, tremor_mm=0.0):
    return PerformancePhase(
        phase_id=f"ph{order}",
        order=order,
        t_start_s=t0,
        t_end_s=t1,
        label="举枪",
        prop_performance=[
            PropPerformance(
                prop_ref="手枪",
                prop_type="firearm",
                material="metal",
                contact_state=PropContactState(
                    state=state,
                    transition_from=transition_from,
                    hold_reason="将扣未扣" if state == "threshold" else "",
                ),
                tremor=PropTremor(amplitude_mm=tremor_mm, source="muscle_fatigue"),
            )
        ],
        body=PerformanceBody(breath="shallow_rapid"),
    )


# 标尺「10秒举枪」手指状态机:扳机面→施压→临界→减压→抬起(逐级合法)
def _four_stage_gun_track():
    return PerformanceTrack(
        total_duration_s=10.0,
        phases=[
            _firearm_phase(1, 0.0, 2.0, "face", "guard"),
            _firearm_phase(2, 2.0, 4.0, "pressure_building", "face"),
            _firearm_phase(3, 4.0, 6.0, "threshold", "pressure_building", tremor_mm=0.8),
            _firearm_phase(4, 6.0, 8.0, "releasing", "threshold"),
            _firearm_phase(5, 8.0, 10.0, "lifted", "releasing"),
        ],
    )


def test_prop_state_machine_compiles():
    """道具接触状态机 + 临界动机编译进时序提示词(§4.5 举枪四阶段)。"""
    line = compile_temporal_prompt(_four_stage_gun_track())
    assert "道具:" in line
    assert "手指滑上扳机面" in line
    assert "施加初始压力" in line
    assert "压力停在临界(将扣未扣)" in line  # threshold + hold_reason
    assert "手指抬起悬停" in line


def test_p7_prop_state_transition():
    """P7:合法逐级转移过;guard→threshold 跳过施压 → 拦。"""
    assert [f for f in lint_performance_track(_four_stage_gun_track()) if f.rule == "P7"] == []
    bad = PerformanceTrack(
        total_duration_s=5.0,
        phases=[
            _firearm_phase(1, 0.0, 2.5, "guard", "guard"),
            _firearm_phase(2, 2.5, 5.0, "threshold", "guard"),  # guard→threshold 非法
        ],
    )
    assert any(
        f.rule == "P7" and "guard→threshold" in f.message for f in lint_performance_track(bad)
    )


def test_sound_derivation_from_physiology_and_prop():
    """§4.6.1:吞咽→吞咽声、破碎呼吸、金属颤动→震响,自动派生。"""
    ph = PerformancePhase(
        phase_id="p1",
        order=1,
        t_start_s=0.0,
        t_end_s=3.0,
        facial_performance=FacialPerformance(physiology=FacialPhysiology(swallow=True)),
        body=PerformanceBody(breath="ragged"),
        prop_performance=[
            PropPerformance(
                prop_type="firearm", material="metal", tremor=PropTremor(amplitude_mm=0.5)
            )
        ],
    )
    sounds = derive_sounds_for_phase(ph)
    assert any("吞咽" in s for s in sounds)
    assert any("破碎的呼吸" in s for s in sounds)
    assert any("震响" in s for s in sounds)


def test_p8_audio_sync_swallow():
    """P8:吞咽的时间窗有派生吞咽声 → 咬合过;人为抹掉声音 → 拦。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="p1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                facial_performance=FacialPerformance(physiology=FacialPhysiology(swallow=True)),
            )
        ],
    )
    audio = derive_audio_track(track)  # 自动派生 → 吞咽声在同窗
    assert lint_audio_sync(track, audio) == []
    # 抹掉派生声音 → P8 拦
    audio.segments[0].derived_sounds = []
    assert any(f.rule == "P8" and "吞咽" in f.message for f in lint_audio_sync(track, audio))


def test_derive_occlusion_from_posture():
    """§4.7:低头 → 面部阴影加深(occlusion 由 body.posture 推导)。"""
    occ = derive_occlusion(PerformanceBody(posture="他微微低头"))
    assert occ is not None and occ.shadow_delta == "deepen" and occ.affected_area == "面部"
    assert derive_occlusion(PerformanceBody(posture="正视前方")) is None


def test_lighting_compiles_and_p9():
    """光响应编译 + P9(阴影变化无遮挡原因 → 拦)。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[
            PerformancePhase(
                phase_id="p1",
                order=1,
                t_start_s=0.0,
                t_end_s=3.0,
                lighting_response=LightingResponse(
                    key_ratio=LightingKeyRatio(
                        lit_side="右半脸", shadow_side="左半脸深阴影", contrast_level=0.85
                    ),
                    occlusion=LightingOcclusion(
                        cause="头部低垂", affected_area="面部", shadow_delta="deepen"
                    ),
                ),
            )
        ],
    )
    line = compile_temporal_prompt(track)
    assert "光:" in line and "受光右半脸" in line and "头部低垂使面部阴影加深" in line
    assert [f for f in lint_performance_track(track) if f.rule == "P9"] == []
    # 阴影变了但没说原因 → P9
    track.phases[0].lighting_response.occlusion.cause = ""
    assert any(f.rule == "P9" for f in lint_performance_track(track))


def test_derive_negatives_from_schema():
    """§5.5:有枪+手 → 自动"不要多余手指/枪械变形";无配乐/无台词 → 自动出现。"""
    shot = ShotListItem(
        shot_id="SH001",
        scene_no=1,
        performance_track=_four_stage_gun_track(),
        audio_track=AudioTrack(),
    )  # music/dialogue 空
    neg = derive_negatives(shot)
    assert "不要枪械结构变形" in neg and "不要多余或畸形的手指" in neg
    assert "不要背景音乐" in neg and "不要台词/对白声" in neg
    assert "不要卡通/动漫感" in neg


def test_compile_audio_prompt():
    """声音提示词第四层:无配乐无台词头 + 逐段声音 + 环境声。"""
    track = _four_stage_gun_track()
    audio = derive_audio_track(track)
    audio.ambient.bed = "远处环境低鸣"
    audio.ambient.evolution = "fade_in"
    out = compile_audio_prompt(audio)
    assert out.startswith("(无配乐、无台词)")
    assert "[4–6s]" in out and "震响" in out  # phase3(临界)金属颤动派生
    assert "环境声:远处环境低鸣(渐显)" in out


def test_v02_all_inert_when_absent():
    """未填道具/光/声音 → 编译无对应段、派生无 finding(向后兼容 inert)。"""
    track = PerformanceTrack(
        total_duration_s=3.0,
        phases=[PerformancePhase(phase_id="p1", order=1, t_start_s=0.0, t_end_s=3.0, label="x")],
    )
    line = compile_temporal_prompt(track)
    assert "道具:" not in line and "光:" not in line
    assert lint_audio_sync(track, None) == []
    assert derive_audio_track(None) is None
    assert compile_audio_prompt(None) == ""
