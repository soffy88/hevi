"""RFC-002 item 6: ASR 强制对齐字幕 —— 用 faster-whisper 转写旁白音频,
生成时间码精确的 SRT,取代 omodul 的规划时长字幕(会漂移)。

设计: 转写在 CPU 上跑(base 模型小, 避免与 wan 抢 GPU)。SRT 格式化为纯函数,
可不依赖模型单测。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# faster-whisper 模型目录: 优先 env, 兜底本地 base。
_MODEL_DIR = os.environ.get(
    "FASTER_WHISPER_MODEL_DIR",
    str(Path.home() / "models/faster-whisper-base"),
)


@dataclass(frozen=True)
class Cue:
    """一条字幕: 起止秒 + 文本。"""

    start: float
    end: float
    text: str


def _fmt_ts(seconds: float) -> str:
    """秒 → SRT 时间码 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
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


def transcribe_to_cues(
    audio_path: Path, *, language: str | None = None, model_dir: str | None = None,
) -> list[Cue]:
    """用 faster-whisper 转写音频为带时间码的字幕段(强制对齐)。"""
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]

    model = WhisperModel(model_dir or _MODEL_DIR, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio_path), language=language, vad_filter=True)
    cues: list[Cue] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            cues.append(Cue(start=float(seg.start), end=float(seg.end), text=text))
    return cues


async def align_subtitles(
    audio_path: Path, output_srt: Path, *, language: str | None = None,
) -> Path | None:
    """转写旁白 → 写 ASR 对齐 SRT。失败返回 None(装配器据此跳过烧字幕)。

    在线程池跑(faster-whisper 是同步 CPU 调用),不阻塞事件循环。
    """
    import asyncio

    if not audio_path.exists():
        return None
    try:
        cues = await asyncio.to_thread(
            transcribe_to_cues, audio_path, language=language,
        )
    except Exception:
        return None
    if not cues:
        return None
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(cues_to_srt(cues), encoding="utf-8")
    return output_srt
