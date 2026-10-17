"""视频转录 —— faster-whisper / whisperX 本地转录。

输出带时间戳的字幕(SRT + word-level JSON),供参考视频分析、字幕生成等下游消费。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration_s: float
    segments: list[TranscriptSegment]
    srt_path: Path | None = None
    json_path: Path | None = None

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments)


def transcribe_video(
    video_path: Path,
    output_dir: Path,
    *,
    model_size: str = "base",
    language: str | None = None,
    word_timestamps: bool = True,
) -> Transcript:
    """转录视频音频为带时间戳的文本。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录(SRT + JSON)
        model_size: tiny / base / small / medium / large-v3
        language: 强制语言代码(如 zh / en / ja),None=自动检测
        word_timestamps: 是否输出词级时间戳

    Returns:
        Transcript 对象
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        return _transcribe_faster_whisper(
            video_path, output_dir,
            model_size=model_size, language=language,
            word_timestamps=word_timestamps,
        )
    except (ImportError, RuntimeError):
        return _transcribe_ffmpeg_subprocess(video_path, output_dir)


def _transcribe_faster_whisper(
    video_path: Path,
    output_dir: Path,
    *,
    model_size: str,
    language: str | None,
    word_timestamps: bool,
) -> Transcript:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="auto", compute_type="auto")
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language,
        word_timestamps=word_timestamps,
        beam_size=5,
    )

    segments = []
    for seg in segments_iter:
        words = []
        if word_timestamps and seg.words:
            words = [{"word": w.word, "start": w.start, "end": w.end} for w in seg.words]
        segments.append(TranscriptSegment(
            start=seg.start, end=seg.end, text=seg.text.strip(), words=words,
        ))

    # 写 SRT
    srt_path = output_dir / f"{video_path.stem}.srt"
    _write_srt(segments, srt_path)

    # 写 JSON
    json_path = output_dir / f"{video_path.stem}_transcript.json"
    import json
    json_path.write_text(json.dumps({
        "language": info.language,
        "duration": info.duration,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text, "words": s.words}
            for s in segments
        ],
    }, ensure_ascii=False, indent=2))

    return Transcript(
        language=info.language,
        duration_s=info.duration,
        segments=segments,
        srt_path=srt_path,
        json_path=json_path,
    )


def _transcribe_ffmpeg_subprocess(video_path: Path, output_dir: Path) -> Transcript:
    """无 whisper 回退:提取音轨 + 空转录(至少让下游知道时长)。"""

    # 用 ffprobe 获取时长
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0

    return Transcript(
        language="unknown",
        duration_s=duration,
        segments=[],
    )


def _write_srt(segments: list[TranscriptSegment], path: Path) -> None:
    def _fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(f"{i}")
        lines.append(f"{_fmt(seg.start)} --> {_fmt(seg.end)}")
        lines.append(seg.text)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
