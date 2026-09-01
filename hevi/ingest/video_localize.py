"""外语视频 → 中文字幕成片计划 —— 对照 xiaohu-video-md 一条龙(不配音)。

下载/转写走既有 ingest;本模块负责切句、润色、ASS、一次编码烧录命令。
翻译需要 LLM 时由调用方注入 translated 段;缺失则只出原文字幕并在 notes 标明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hevi.assembly.subtitle_burner import get_subtitle_filter
from hevi.ingest.ass_captions import cues_to_ass
from hevi.ingest.speakers import label_speakers
from hevi.ingest.subtitle_polish import polish_segments
from hevi.ingest.video_transcript import TranscriptSegment
from hevi.ingest.words import flatten_words, split_cues_by_pause


@dataclass
class LocalizePlan:
    """译制烧录计划。burn_args 可直接喂 ffmpeg;未给成片时 video_path 可空。"""

    ass_text: str
    ass_path: str
    bilingual: bool
    segments: list[TranscriptSegment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    burn_args: list[str] = field(default_factory=list)
    video_path: str = ""
    output_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ass_path": self.ass_path,
            "bilingual": self.bilingual,
            "notes": list(self.notes),
            "burn_args": list(self.burn_args),
            "video_path": self.video_path,
            "output_path": self.output_path,
            "cues": len(self.segments),
        }


def plan_localize(
    source_segments: list[TranscriptSegment],
    *,
    translated: list[TranscriptSegment] | None = None,
    bilingual: bool = True,
    glossary: dict[str, str] | None = None,
    speakers: bool = False,
    work_dir: Path,
    video_path: str | Path = "",
    output_path: str | Path = "",
    watermark: str = "",
) -> LocalizePlan:
    """从转写做出 ASS + ffmpeg 烧录参数。不跑 ffmpeg。"""
    notes: list[str] = []
    words = flatten_words(source_segments)
    cues = split_cues_by_pause(words) if words else list(source_segments)
    cues = polish_segments(cues, glossary=glossary)
    if speakers:
        cues = label_speakers(cues)
        notes.append("speakers=heuristic-pause")

    trans = polish_segments(translated, glossary=glossary) if translated else None
    if bilingual and not trans:
        notes.append("bilingual requested but no translation; primary-only ASS")
        bilingual = False

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    ass_path = work_dir / "subtitles.ass"
    if bilingual and trans is not None:
        n = min(len(cues), len(trans))
        pairs = list(zip(trans[:n], cues[:n], strict=False))
        ass_text = cues_to_ass(pairs, bilingual=True)
        segments = trans[:n]
    else:
        ass_text = cues_to_ass(cues, bilingual=False)
        segments = cues
    ass_path.write_text(ass_text, encoding="utf-8")

    video = str(video_path or "")
    dest = str(output_path or (work_dir / "localized.mp4"))
    burn_args: list[str] = []
    if video:
        burn_args = ffmpeg_burn_args(video, ass_path, dest, watermark=watermark)
    else:
        notes.append("no video_path; ASS written, burn skipped")

    return LocalizePlan(
        ass_text=ass_text,
        ass_path=str(ass_path),
        bilingual=bilingual,
        segments=segments,
        notes=notes,
        burn_args=burn_args,
        video_path=video,
        output_path=dest,
    )


def ffmpeg_burn_args(
    video_path: str | Path,
    ass_path: str | Path,
    output_path: str | Path,
    *,
    watermark: str = "",
) -> list[str]:
    """一次编码烧字幕(+可选水印)。对照 xiaohu:burn-in + watermark in one encode。"""
    filt = get_subtitle_filter(Path(ass_path), style="large_white")
    if watermark.strip():
        text = watermark.replace("\\", "\\\\").replace("'", r"\'").replace(":", r"\:")
        filt = f"{filt},drawtext=text='{text}':x=w-tw-24:y=24:fontsize=20:fontcolor=white@0.7"
    return [
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filt,
        "-c:v",
        "libx264",
        "-c:a",
        "copy",
        str(output_path),
    ]
