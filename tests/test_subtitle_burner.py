"""hevi.assembly.subtitle_burner 测试 —— 字幕烧录样式预设(纯字符串拼接,无需 ffmpeg)。"""

from __future__ import annotations

from pathlib import Path

from hevi.assembly.subtitle_burner import get_subtitle_filter


def test_default_style_no_force_style() -> None:
    f = get_subtitle_filter(Path("sub.srt"))
    assert f == "subtitles='sub.srt'"


def test_bold_yellow_preset() -> None:
    f = get_subtitle_filter(Path("sub.srt"), style="bold_yellow")
    assert "force_style=" in f
    assert "PrimaryColour=&H00FFFF" in f


def test_large_white_preset() -> None:
    f = get_subtitle_filter(Path("sub.srt"), style="large_white")
    assert "FontSize=28" in f


def test_compact_preset() -> None:
    f = get_subtitle_filter(Path("sub.srt"), style="compact")
    assert "MarginV=16" in f


def test_unknown_style_falls_back_to_default() -> None:
    f = get_subtitle_filter(Path("sub.srt"), style="bogus")
    assert f == "subtitles='sub.srt'"


def test_path_escaping() -> None:
    f = get_subtitle_filter(Path("C:/videos/sub.srt"))
    assert "C\\:/videos/sub.srt" in f
