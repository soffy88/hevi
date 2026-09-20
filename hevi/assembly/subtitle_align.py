"""RFC-002 item 6: ASR 强制对齐字幕 —— 用 oprim.transcribe_audio 转写旁白音频,
生成时间码精确的 SRT,取代 omodul 的规划时长字幕(会漂移)。

设计: 转写在 CPU 上跑(base 模型小, 避免与 wan 抢 GPU)。SRT 格式化为纯函数,
可不依赖模型单测。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oprim import TranscriptResult, transcribe_audio

# faster-whisper 模型目录: 优先 env, 兜底本地 large-v3-turbo。
DEFAULT_ASR_MODEL_DIR = os.environ.get(
    "FASTER_WHISPER_MODEL_DIR",
    str(Path.home() / "models/faster-whisper-large-v3-turbo"),
)


@dataclass(frozen=True)
class Cue:
    """一条字幕: 起止秒 + 文本(+ 可选情感标注, 情感感知配音用)。"""

    start: float
    end: float
    text: str
    emotion: str = "neutral"  # happy/sad/angry/calm/nervous/excited/neutral


def _fmt_ts(seconds: float) -> str:
    """秒 → SRT 时间码 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def cues_to_srt(cues: list[Cue]) -> str:
    """字幕列表 → SRT 文本。"""
    blocks: list[str] = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_fmt_ts(c.start)} --> {_fmt_ts(c.end)}\n{c.text.strip()}\n")
    return "\n".join(blocks)


def transcript_result_to_cues(result: TranscriptResult) -> list[Cue]:
    """Convert oprim TranscriptResult to Cue list."""
    cues: list[Cue] = []
    for seg in result.segments:
        text = (seg.get("text") or "").strip()
        if text:
            cues.append(Cue(start=float(seg["start"]), end=float(seg["end"]), text=text))
    return cues


async def align_subtitles(
    audio_path: Path,
    output_srt: Path,
    *,
    language: str | None = None,
    backend: str = "local",
    model_size: str = "base",
    model_path: str | None = None,
) -> Path | None:
    """转写旁白 → 写 ASR 对齐 SRT。失败返回 None(装配器据此跳过烧字幕)。

    使用 oprim.transcribe_audio 规范原语。
    """
    if not audio_path.exists():
        return None
    try:
        result = await transcribe_audio(
            audio_path=audio_path,
            backend=backend,
            model_size=model_size,
            language=language or "zh",
            model_path=model_path or DEFAULT_ASR_MODEL_DIR,
            vad_filter=True,
        )
    except Exception:
        return None

    cues = transcript_result_to_cues(result)
    if not cues:
        return None

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(cues_to_srt(cues), encoding="utf-8")
    return output_srt


def merge_bilingual_cues(primary: list[Cue], secondary: list[Cue]) -> list[Cue]:
    """两份同时间码的字幕(原文 + 译文)→ 每条 cue 两行文本(原文换行译文)。

    标准双语字幕做法:同一 cue 块内两行文本,而非两条独立 cue(避免叠字幕/抢时间轴)。
    以 primary 的时间码为准;secondary 缺对应行则只留原文那一行。
    """
    merged: list[Cue] = []
    for i, c in enumerate(primary):
        t = secondary[i].text if i < len(secondary) else ""
        text = f"{c.text}\n{t}" if t else c.text
        merged.append(Cue(start=c.start, end=c.end, text=text))
    return merged


async def align_subtitles_bilingual(
    audio_path: Path,
    output_srt: Path,
    *,
    source_language: str | None = None,
    target_language: str,
    llm: Any = None,
    backend: str = "local",
    model_size: str = "base",
    model_path: str | None = None,
) -> Path | None:
    """转写旁白 → 翻译 → 双语 SRT(每条 cue 原文+译文两行,同时间码)。

    复用 oprim.transcribe_audio + translate_cues(§3 L2 已有的 dub 翻译步骤,保时间码)。
    任一步失败 → None,装配器据此跳过烧字幕(不阻断出片)。
    """
    from hevi.dub.translate import translate_cues

    if not audio_path.exists():
        return None
    try:
        result = await transcribe_audio(
            audio_path=audio_path,
            backend=backend,
            model_size=model_size,
            language=source_language or "zh",
            model_path=model_path or DEFAULT_ASR_MODEL_DIR,
            vad_filter=True,
        )
        if not result.segments:
            return None
        cues = transcript_result_to_cues(result)
        tcues = await translate_cues(cues, target_language=target_language, llm=llm)
        merged = merge_bilingual_cues(cues, tcues)
    except Exception:
        return None
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(cues_to_srt(merged), encoding="utf-8")
    return output_srt