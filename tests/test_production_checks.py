"""production_checks 测试 —— 生产侧确定性质量检查(差距 B4)。

覆盖: 场景节奏/音频边界/集独立性/声音稳定性/汇总执行/异常隔离。
"""

from __future__ import annotations

from hevi.verdict.production_checks import (
    check_audio_boundaries,
    check_episode_independence,
    check_scene_pacing,
    check_voice_stability,
    run_production_checks,
)


def test_scene_pacing_pass():
    scenes = [{"id": i, "duration_s": 8.0} for i in range(4)]
    r = check_scene_pacing(scenes)
    assert r.passed


def test_scene_pacing_too_short():
    scenes = [{"id": "a", "duration_s": 0.4}, {"id": "b", "duration_s": 8.0}]
    r = check_scene_pacing(scenes)
    assert not r.passed
    assert "过短" in r.details[0]


def test_scene_pacing_too_long():
    scenes = [{"id": "a", "duration_s": 90.0}]
    r = check_scene_pacing(scenes)
    assert not r.passed
    assert "过长" in r.details[0]


def test_scene_pacing_missing_duration():
    r = check_scene_pacing([{"id": "a"}, {"id": "b", "duration_s": 5.0}])
    assert r.passed  # 有数据项通过, 缺时长的只记 note


def test_scene_pacing_empty():
    assert not check_scene_pacing([]).passed


def test_scene_pacing_high_cv():
    scenes = [{"id": i, "duration_s": d} for i, d in enumerate([0.5, 5.0, 90.0])]
    r = check_scene_pacing(scenes, min_s=0.3, max_s=95.0)
    assert "离散度" in " ".join(r.details)


def test_audio_boundaries_pass():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 2.2, "end": 4.0}]
    assert check_audio_boundaries(segs).passed


def test_audio_boundaries_overlap():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 1.9, "end": 3.0}]
    r = check_audio_boundaries(segs)
    assert not r.passed
    assert "重叠" in r.details[0]


def test_audio_boundaries_tiny_gap_note():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 2.01, "end": 3.0}]
    r = check_audio_boundaries(segs)
    assert r.passed  # 微小间隙只记 note 不判失败


def test_audio_boundaries_unsorted_input():
    segs = [{"start": 2.0, "end": 3.0}, {"start": 0.0, "end": 1.0}]
    assert check_audio_boundaries(segs).passed  # 自动排序


def test_audio_boundaries_no_data():
    assert not check_audio_boundaries([]).passed


def test_episode_independence_pass():
    ep = {
        "title": "E3 深渊",
        "recap_present": True,
        "cliffhanger_present": True,
        "self_contained_refs": True,
        "cold_open": True,
    }
    assert check_episode_independence(ep).passed


def test_episode_independence_missing_recap():
    ep = {"title": "E3", "recap_present": False, "cold_open": False, "cliffhanger_present": True, "self_contained_refs": True}
    r = check_episode_independence(ep)
    assert not r.passed


def test_episode_independence_forward_refs():
    ep = {"title": "E3", "recap_present": True, "cliffhanger_present": True, "self_contained_refs": False}
    r = check_episode_independence(ep)
    assert not r.passed
    assert "自包含" in r.details[0]


def test_voice_stability_pass():
    stats = [{"rms": 0.30, "pitch_hz": 180}, {"rms": 0.32, "pitch_hz": 182}, {"rms": 0.31, "pitch_hz": 179}]
    assert check_voice_stability(stats).passed


def test_voice_stability_loudness_drift():
    stats = [{"rms": 0.1, "pitch_hz": 180}, {"rms": 0.9, "pitch_hz": 182}]
    r = check_voice_stability(stats)
    assert not r.passed
    assert "响度不稳定" in r.details[0]


def test_voice_stability_pitch_drift():
    stats = [{"rms": 0.3, "pitch_hz": 160}, {"rms": 0.31, "pitch_hz": 260}]
    r = check_voice_stability(stats)
    assert not r.passed
    assert "基频漂移" in r.details[0]


def test_voice_stability_no_data():
    assert not check_voice_stability([]).passed


def test_voice_stability_single_segment_notes():
    r = check_voice_stability([{"rms": 0.3, "pitch_hz": 180}])
    assert r.passed
    assert any("从宽" in d for d in r.details)


def test_run_production_checks_all_pass():
    def _pacing():
        return check_scene_pacing([{"id": "a", "duration_s": 8.0}])

    def _boundaries():
        return check_audio_boundaries([{"start": 0.0, "end": 1.0}])

    out = run_production_checks({"scene_pacing": _pacing, "audio_boundaries": _boundaries})
    assert out["passed"] is True
    assert out["failed_count"] == 0
    assert len(out["checks"]) == 2


def test_run_production_checks_failure_and_isolation():
    def _bad():
        raise RuntimeError("boom")

    def _ok():
        return check_scene_pacing([{"id": "a", "duration_s": 8.0}])

    out = run_production_checks([("bad", _bad), ("ok", _ok)])
    assert out["passed"] is False
    assert out["failed_count"] == 1
    names = [c["name"] for c in out["checks"]]
    assert names == ["bad", "ok"]
    assert "检查器异常" in out["checks"][0]["details"][0]
