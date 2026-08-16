"""Round 3i(oil-motion 内化)测试: 交互映射 / 帧预算 / 资源决策 / 图集预算 / 清单。"""

from __future__ import annotations

import math

import pytest

from hevi.motion.interactive import (
    atlas_budget,
    atlas_css_background,
    build_atlas_manifest,
    decide_resource_form,
    interactive_frame_budget,
    map_input_to_frame,
    ring_shortest_delta,
    save_atlas_manifest,
)

# ---- 帧预算(独立姿态数)----

def test_frame_budget_by_control():
    assert interactive_frame_budget("scroll", scroll_pages=1.0) == 24
    assert interactive_frame_budget("scroll", scroll_pages=4.0) == 96  # 4 屏基线
    assert interactive_frame_budget("drag") == 48
    assert interactive_frame_budget("ring") == 72
    assert interactive_frame_budget("state") == 8
    with pytest.raises(ValueError):
        interactive_frame_budget("nope")


# ---- 输入→帧映射 ----

def test_map_scroll_linear():
    assert map_input_to_frame(0.0, 100) == 0
    assert map_input_to_frame(0.3, 100) == 29  # int(0.3*99)
    assert map_input_to_frame(1.0, 100) == 99
    assert map_input_to_frame(2.0, 100) == 99  # clamp
    assert map_input_to_frame(-1.0, 100) == 0
    assert map_input_to_frame(0.5, 1) == 0  # 单帧


def test_map_ring_angle():
    # 0 弧度 → 帧 0;π 弧度(半圈)→ 帧 count/2
    assert map_input_to_frame(0.0, 72, mapping="ring") == 0
    assert map_input_to_frame(math.pi, 72, mapping="ring") == 36  # 精确半圈
    # 环形连续:2π 与 0 同帧;负角等价 mod
    assert map_input_to_frame(2 * math.pi, 72, mapping="ring") == 0
    assert map_input_to_frame(-math.pi, 72, mapping="ring") == 36


def test_ring_shortest_delta():
    # 环形最短距离:count=72, target=2 current=70 → 直距 -68,环距 +4
    assert ring_shortest_delta(2, 70, 72) == 4
    assert ring_shortest_delta(70, 2, 72) == -4
    assert ring_shortest_delta(36, 36, 72) == 0
    assert ring_shortest_delta(0, 0, 0) == 0


# ---- 资源形式决策 ----

def _decide(**kw: object) -> str:
    return decide_resource_form(**kw)  # type: ignore[arg-type]


def test_decide_resource_form():
    # 透明 + <300 帧 → webp_atlas
    assert (
        _decide(transparency=True, frames=200, display_size=(240, 240), control_kind="scroll")
        == "webp_atlas"
    )
    # 长顺序滚动 → seekable_video
    assert (
        _decide(transparency=False, frames=400, display_size=(1920, 1080), control_kind="scroll")
        == "seekable_video"
    )
    # 高分辨率一维频繁 seek → keyframe_mp4
    assert (
        _decide(transparency=False, frames=200, display_size=(1920, 1080), control_kind="scroll")
        == "keyframe_mp4"
    )
    # hover/click → short_clips
    assert (
        _decide(transparency=True, frames=10, display_size=(100, 100), control_kind="state")
        == "short_clips"
    )
    # WebCodecs 目标明确
    assert _decide(
        transparency=True, frames=200, display_size=(240, 240), control_kind="scroll",
        target_browser="webcodecs",
    ) == "webcodecs"
    # 图集超纹理上限 → sliced_atlas
    assert (
        _decide(transparency=True, frames=200, display_size=(1000, 1000), control_kind="ring")
        == "sliced_atlas"
    )


# ---- 图集预算 ----

def test_atlas_budget_basic():
    res = atlas_budget(display_size=(240, 240), dpr=2.0, frames=180)
    assert res.cell_width == 480 and res.cell_height == 480
    assert res.cols * res.rows >= 180
    expected = res.texture_width * res.texture_height * 4 / (1024 * 1024)
    assert res.decode_memory_mb == pytest.approx(expected, abs=0.01)


def test_atlas_budget_texture_overflow():
    # 大显示 × 高 DPR × 多帧 → 超 4096 → within_texture_limit False + note
    res = atlas_budget(display_size=(1024, 1024), dpr=3.0, frames=400)
    assert not res.within_texture_limit
    assert any("超纹理上限" in n for n in res.notes)


def test_atlas_budget_cell_respects_dpr():
    # 单元 ≥ 显示尺寸 × DPR(禁止低分辨率放大)
    res = atlas_budget(display_size=(300, 300), dpr=1.25, frames=96)
    assert res.cell_width == 375 and res.cell_height == 375


# ---- 清单 ----

def test_atlas_manifest_and_css():
    manifest = build_atlas_manifest(
        frames=180, cols=15, rows=12, cell_width=480, cell_height=480,
        anchor=(0.5, 0.5), mapping="scroll", static_frames=[0],
    )
    assert manifest.frames == 180
    assert atlas_css_background(manifest) == "1500% 1200%"
    d = manifest.to_dict()
    assert d["cols"] == 15 and d["rows"] == 12


def test_save_atlas_manifest(tmp_path):
    manifest = build_atlas_manifest(frames=24, cols=6, rows=4, cell_width=480, cell_height=480)
    p = save_atlas_manifest(manifest, tmp_path / "manifest.json")
    assert p.exists()
    data = __import__("json").loads(p.read_text(encoding="utf-8"))
    assert data["frames"] == 24


# ---- CLI ----

def test_interactive_cli_budget(capsys):
    from hevi.skills.interactive_cli import main

    # 96 帧 / 300px 单元(10x10 → 3000x3000)在纹理上限内 → rc 0
    rc = main(
        ["budget", "--display", "240x240", "--dpr", "1.25", "--frames", "96"]
    )
    assert rc == 0
    assert "cell_width" in capsys.readouterr().out
    # 180 帧 / 480px 单元超 4096 → rc 1(正确提示分片/视频解码)
    rc2 = main(
        ["budget", "--display", "240x240", "--dpr", "2", "--frames", "180"]
    )
    assert rc2 == 1


def test_interactive_cli_decide(capsys):
    from hevi.skills.interactive_cli import main

    main(
        [
            "decide", "--transparency", "--frames", "200",
            "--display", "240x240", "--control", "scroll",
        ]
    )
    assert capsys.readouterr().out.strip() == "webp_atlas"
