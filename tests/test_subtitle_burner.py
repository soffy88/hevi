"""hevi.assembly.subtitle_burner 测试 —— 字幕烧录样式预设(纯字符串拼接,无需 ffmpeg)。"""

from __future__ import annotations

from pathlib import Path

from hevi.assembly.subtitle_burner import get_subtitle_filter


def test_default_style_still_forces_cjk_font() -> None:
    # default 也必须带 CJK 字体,否则中文烧成豆腐块(2026-07-14 线上实测)。
    f = get_subtitle_filter(Path("sub.srt"))
    assert f == "subtitles='sub.srt':force_style='FontName=Noto Sans CJK SC'"


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


def test_unknown_style_falls_back_to_cjk_font_only() -> None:
    f = get_subtitle_filter(Path("sub.srt"), style="bogus")
    assert f == "subtitles='sub.srt':force_style='FontName=Noto Sans CJK SC'"


def test_all_presets_include_cjk_font() -> None:
    for style in ("bold_yellow", "large_white", "compact"):
        assert "FontName=Noto Sans CJK SC" in get_subtitle_filter(Path("s.srt"), style=style)


def test_path_escaping() -> None:
    f = get_subtitle_filter(Path("C:/videos/sub.srt"))
    assert "C\\:/videos/sub.srt" in f
