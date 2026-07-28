"""三档置信角标模板测试(LSXC-EP0-CHARTER §3 频道视觉契约)。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.assembly.tier_overlay import _TIERS, burn_tier_overlay, render_tier_badge

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_only = pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg")


def test_three_tiers_frozen_contract() -> None:
    # 频道契约:恰三档,三色互异(不允许悄悄改)
    assert set(_TIERS) == {"实录", "推演", "演绎"}
    colors = [t["rgb"] for t in _TIERS.values()]
    assert len(set(colors)) == 3
    assert _TIERS["实录"]["rgb"] == (46, 109, 180)  # 青蓝,冻结


@pytest.mark.parametrize("tier", ["实录", "推演", "演绎"])
def test_render_badge_produces_png(tier: str, tmp_path: Path) -> None:
    out = tmp_path / f"{tier}.png"
    w, h = render_tier_badge(tier, out, height=56)
    assert out.exists() and out.stat().st_size > 0
    assert w > 0 and h >= 56


def test_render_badge_cite_makes_it_taller() -> None:
    # 实录挂出处 → 多一行,比无出处高
    _, h_plain = render_tier_badge("实录", Path("/tmp/_t_plain.png"), height=56)
    _, h_cite = render_tier_badge(
        "实录", Path("/tmp/_t_cite.png"), height=56, cite="史记·秦始皇本纪"
    )
    assert h_cite > h_plain


def test_unknown_tier_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        render_tier_badge("野史", tmp_path / "x.png")


@ffmpeg_only
def test_burn_overlay_on_clip(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=gray:size=360x640:duration=1:rate=8",
            str(src),
        ],
        check=True,
    )
    out = burn_tier_overlay(src, tmp_path / "out.mp4", "演绎")
    assert out.exists() and out.stat().st_size > 0
