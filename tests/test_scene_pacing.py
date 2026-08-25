"""scene_pacing 测试 —— 帧精确步骤时间轴 + narration cue 对齐断言。

覆盖: 各步骤 kind 时长计算 / trace 里程碑 / 对齐断言(失配、溢出、欠填)。
"""

from __future__ import annotations

import pytest

from hevi.verdict.scene_pacing import assert_alignment, step_duration, trace

# 模拟合成 UI 场景: 安装步骤 + 旁白 cue。
INSTALL_STEPS = [
    {"kind": "cmd", "text": "git clone https://github.com/example/repo", "typeSpeed": 0.035, "holdSeconds": 0.3},
    {"kind": "out", "text": "Cloning into 'repo'...", "holdSeconds": 0.15},
    {"kind": "cmd", "text": "make setup", "typeSpeed": 0.035, "holdSeconds": 0.3},
    {"kind": "pause", "seconds": 2.0},
    {"kind": "cmd", "text": "open .", "typeSpeed": 0.035, "holdSeconds": 0.3},
    {"kind": "pill", "text": "reading guide", "holdSeconds": 0.0},
]


def test_step_duration_kinds() -> None:
    # cmd: 打字帧数(取整) + hold —— 3 字符 × 0.035 × 30 = 3.15 → ceil 4 帧 = 0.133
    d = step_duration({"kind": "cmd", "text": "abc", "typeSpeed": 0.035, "holdSeconds": 0.3}, fps=30)
    assert d == pytest.approx(0.1333 + 0.3, abs=1 / 30)
    # out: 固定 0.08s reveal(2 帧) + hold
    d = step_duration({"kind": "out", "holdSeconds": 0.15}, fps=30)
    assert d == pytest.approx(0.08 + 0.15, abs=1 / 30)
    # pause / pill
    assert step_duration({"kind": "pause", "seconds": 2.0}) == 2.0
    assert step_duration({"kind": "pill"}) == 0.0


def test_step_duration_unknown_kind_raises() -> None:
    with pytest.raises(ValueError):
        step_duration({"kind": "nope"})


def test_trace_marks_visible_events() -> None:
    marks = trace(INSTALL_STEPS, scene_start=50.0, quiet=True)
    # 三个 cmd + 一个 out + 一个 pill 可见(共 5 个里程碑)
    assert [m.kind for m in marks] == ["CMD", "OUT", "CMD", "CMD", "PILL"]
    assert marks[0].video_time == pytest.approx(50.0)
    # 第二个 cmd 在第一个 cmd + out 之后
    assert marks[2].video_time > marks[1].video_time > 50.0


def test_assert_alignment_pass() -> None:
    marks = trace(INSTALL_STEPS, scene_start=50.0, quiet=True)
    cues = [(marks[0].video_time, "clone"), (marks[2].video_time, "setup")]
    total = sum(step_duration(s) for s in INSTALL_STEPS)
    # 不抛异常即通过
    assert_alignment(
        INSTALL_STEPS, scene_start=50.0, scene_end=50.0 + total, narration_cues=cues, tolerance=1.0
    )


def test_assert_alignment_missed_cue_raises() -> None:
    # 里程碑在 ~50/51.77/52.02/54.68/55.22s; cue 放 53.0s, 容差 0.5 → 距最近也 >0.5s
    total = sum(step_duration(s) for s in INSTALL_STEPS)
    with pytest.raises(AssertionError, match="无视觉对齐"):
        assert_alignment(
            INSTALL_STEPS, scene_start=50.0, scene_end=50.0 + total,
            narration_cues=[(53.0, "late cue")], tolerance=0.5,
        )


def test_assert_alignment_overflow_raises() -> None:
    with pytest.raises(AssertionError, match="溢出场景"):
        assert_alignment(
            INSTALL_STEPS, scene_start=50.0, scene_end=51.0,
            narration_cues=[], tolerance=1.0,
        )


def test_assert_alignment_underfill_raises() -> None:
    with pytest.raises(AssertionError, match="欠填场景"):
        assert_alignment(
            INSTALL_STEPS, scene_start=50.0, scene_end=200.0,
            narration_cues=[], tolerance=1.0,
        )
