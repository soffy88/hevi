"""字幕样式系统（对标 video-use bold-overlay + natural-sentence 模式）。

扩展 subtitle_burner.py 的基础样式，增加：
  - bold_overlay: 关键词高亮（粗体+颜色）
  - natural_sentence: 自然句子分段显示
  - karaoke: 逐词高亮（卡拉OK）
  - typewriter: 打字机效果
  - 自定义 ASS 样式模板
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.assembly.edit_craft import SubtitleCue

logger = logging.getLogger(__name__)


# ── CJK 字体（必须，否则中文渲染为豆腐块）────────────────────────────

_CJK_FONT = "Noto Sans CJK SC"


# ── 样式预设 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SubtitleStyle:
    """字幕样式定义。"""

    name: str
    font_size: int = 24
    font_name: str = _CJK_FONT
    primary_colour: str = "&HFFFFFF"  # ASS 格式 &HAABBGGRR
    outline_colour: str = "&H000000"
    back_colour: str = "&H80000000"
    bold: bool = False
    italic: bool = False
    outline: int = 2
    shadow: int = 1
    alignment: int = 2  # ASS 对齐：2=底部居中, 8=顶部居中
    margin_v: int = 30
    margin_l: int = 20
    margin_r: int = 20

    def to_force_style(self) -> str:
        """转为 FFmpeg force_style 参数。"""
        parts = [
            f"FontName={self.font_name}",
            f"FontSize={self.font_size}",
            f"PrimaryColour={self.primary_colour}",
            f"OutlineColour={self.outline_colour}",
            f"BackColour={self.back_colour}",
            f"Bold={int(self.bold)}",
            f"Italic={int(self.italic)}",
            f"Outline={self.outline}",
            f"Shadow={self.shadow}",
            f"Alignment={self.alignment}",
            f"MarginV={self.margin_v}",
            f"MarginL={self.margin_l}",
            f"MarginR={self.margin_r}",
        ]
        return ",".join(parts)


# 预设样式库
SUBTITLE_STYLES: dict[str, SubtitleStyle] = {
    "default": SubtitleStyle(
        name="default",
        font_size=24,
        primary_colour="&HFFFFFF",
        outline=2,
    ),
    "bold_yellow": SubtitleStyle(
        name="bold_yellow",
        font_size=24,
        primary_colour="&H00FFFF",  # 黄色 (BGR)
        bold=True,
        outline=2,
    ),
    "large_white": SubtitleStyle(
        name="large_white",
        font_size=28,
        primary_colour="&HFFFFFF",
        bold=True,
        outline=2,
    ),
    "compact": SubtitleStyle(
        name="compact",
        font_size=18,
        primary_colour="&HFFFFFF",
        margin_v=16,
    ),
    "bold_overlay": SubtitleStyle(
        name="bold_overlay",
        font_size=26,
        primary_colour="&HFFFFFF",
        bold=True,
        outline=3,
        shadow=2,
        margin_v=40,
    ),
    "natural_sentence": SubtitleStyle(
        name="natural_sentence",
        font_size=22,
        primary_colour="&HEEEEEE",
        outline=1,
        shadow=1,
        margin_v=25,
    ),
    "karaoke": SubtitleStyle(
        name="karaoke",
        font_size=26,
        primary_colour="&H00FFFF",  # 高亮黄
        outline_colour="&HFFFFFF",
        bold=True,
        outline=2,
    ),
    "cinematic": SubtitleStyle(
        name="cinematic",
        font_size=20,
        primary_colour="&HDDDDDD",
        outline=1,
        shadow=2,
        margin_v=50,
    ),
}


# ── ASS 生成 ──────────────────────────────────────────────────────────


def _ass_time(seconds: float) -> str:
    """秒 → ASS 时间格式 H:MM:SS.CC"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass_header(style: SubtitleStyle) -> str:
    """生成 ASS 文件头。"""
    return f"""[Script Info]
Title: Hevi Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_name},{style.font_size},{style.primary_colour},&H000000FF,{style.outline_colour},{style.back_colour},{int(style.bold)},{int(style.italic)},0,0,100,100,0,0,1,{style.outline},{style.shadow},{style.alignment},{style.margin_l},{style.margin_r},{style.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def cues_to_ass(
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    *,
    highlight_words: list[str] | None = None,
) -> str:
    """将 SubtitleCue 列表转为 ASS 格式。

    Args:
        cues: 字幕 cue 列表
        style: 样式
        highlight_words: 需要高亮的词列表（用于 bold_overlay 模式）
    """
    lines = [build_ass_header(style)]

    for cue in cues:
        start = _ass_time(cue.start)
        end = _ass_time(cue.end)
        text = cue.text

        # 关键词高亮（bold_overlay 模式）
        if highlight_words:
            for hw in highlight_words:
                if hw in text:
                    text = text.replace(hw, f"{{\\b1}}{hw}{{\\b0}}")

        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


def cues_to_karaoke_ass(
    cues: list[SubtitleCue],
    style: SubtitleStyle,
    *,
    words_with_timing: list[dict[str, Any]] | None = None,
) -> str:
    """生成逐词高亮（卡拉OK）ASS。

    Args:
        cues: 字幕 cue
        style: 样式
        words_with_timing: [{"word": "hello", "start": 0.0, "end": 0.5}, ...]
    """
    lines = [build_ass_header(style)]

    for cue in cues:
        start = _ass_time(cue.start)
        end = _ass_time(cue.end)

        # 如果有词级时间戳，生成逐词高亮
        if words_with_timing:
            cue_words = [
                w for w in words_with_timing
                if w["start"] >= cue.start and w["end"] <= cue.end
            ]
            text_parts = []
            for w in cue_words:
                # \\k 是 ASS 的卡拉OK 效果（持续 centiseconds）
                dur_cs = int((w["end"] - w["start"]) * 100)
                text_parts.append(f"{{\\k{dur_cs}}}{w['word']}")
            text = "".join(text_parts)
        else:
            text = cue.text

        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


# ── FFmpeg 滤镜 ──────────────────────────────────────────────────────


def build_subtitle_filter(
    subtitle_path: Path,
    style_name: str = "default",
    *,
    custom_style: SubtitleStyle | None = None,
) -> str:
    """构建 FFmpeg 字幕烧录滤镜。

    Args:
        subtitle_path: .srt 或 .ass 文件路径
        style_name: 预设样式名
        custom_style: 自定义样式（覆盖预设）
    """
    path_str = str(subtitle_path).replace("\\", "/").replace(":", "\\:")

    style = custom_style or SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES["default"])

    if subtitle_path.suffix == ".ass":
        # ASS 文件自带样式，不强制覆盖
        return f"subtitles='{path_str}'"
    else:
        # SRT 需要 force_style
        force_style = style.to_force_style()
        return f"subtitles='{path_str}':force_style='{force_style}'"


def get_style(name: str) -> SubtitleStyle:
    """获取预设样式。"""
    return SUBTITLE_STYLES.get(name, SUBTITLE_STYLES["default"])


def list_styles() -> list[str]:
    """列出所有可用样式名。"""
    return sorted(SUBTITLE_STYLES.keys())
