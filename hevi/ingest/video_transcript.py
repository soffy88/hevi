"""视频转写 —— 字幕优先,Whisper 兜底(3O 内化 Phase A)。

来源: bradautomates/claude-video 的转写设计:先试原生字幕(免费、快、够准),
没有字幕才走 Whisper(下载音频 → faster-whisper)。本环境无 openai-whisper,
兜底用已在依赖中的 faster-whisper;两者都不可用时给出明确错误。

本模块的核心可测部分是**字幕文件解析**(VTT/SRT → 结构化分段),纯文本解析,
与外部工具解耦。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class TranscriptError(Exception):
    """转写失败。"""


@dataclass(frozen=True)
class TranscriptSegment:
    """一段带时间戳的转写文本。"""

    start: float
    end: float
    text: str


_TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
)


def _ts_to_seconds(ts: str) -> float:
    """把 VTT/SRT 时间戳(00:00:01.500 / 00:01.500 / 1.5)转成秒。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(ts)
    except ValueError as e:
        raise TranscriptError(f"bad timestamp {ts!r}: {e}") from e


def parse_subtitle(content: str) -> list[TranscriptSegment]:
    """解析 VTT 或 SRT 字幕文本为时间戳分段。

    - 按空行切 cue 块;同一 cue 的换行合并为一段(保留原文措辞)。
    - 无时间戳内容 → 空列表(调用方应回退 Whisper)。
    """
    # 去掉 BOM 与 WEBVTT 头部行
    body = content.lstrip("\ufeff").splitlines()
    if body and body[0].strip().upper().startswith("WEBVTT"):
        body = body[1:]
    text = "\n".join(body)

    segs: list[TranscriptSegment] = []
    for block in text.split("\n\n"):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        # 找时间戳行(可能跳过 SRT 序号行)
        ts_line_idx = next(
            (i for i, ln in enumerate(lines) if "-->" in ln), None
        )
        if ts_line_idx is None:
            continue
        m = _TIMESTAMP_RE.search(lines[ts_line_idx])
        if m is None:
            continue
        start = _ts_to_seconds(m.group("start"))
        end = _ts_to_seconds(m.group("end"))
        text_lines = lines[ts_line_idx + 1 :]
        cue_text = " ".join(text_lines)
        if cue_text:
            segs.append(TranscriptSegment(start=start, end=end, text=cue_text))
    segs.sort(key=lambda s: s.start)
    return segs


def read_subtitle_file(path: str | Path) -> list[TranscriptSegment]:
    """读取字幕文件(.vtt/.srt),失败抛 TranscriptError。"""
    p = Path(path)
    if not p.exists():
        raise TranscriptError(f"subtitle file not found: {p}")
    try:
        return parse_subtitle(p.read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        raise TranscriptError(f"cannot read {p}: {e}") from e


def _whisper_transcribe(
    video_path: Path, *, language: str | None = None
) -> list[TranscriptSegment]:
    """faster-whisper 兜底:直接对本地音/视频转写。"""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover - env guard
        raise TranscriptError(f"faster-whisper 未安装,无法兜底转写: {e}") from e

    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(video_path), language=language)
        out: list[TranscriptSegment] = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append(TranscriptSegment(start=float(seg.start), end=float(seg.end), text=text))
        return out
    except Exception as e:
        raise TranscriptError(f"whisper transcription failed: {e}") from e


def fetch_transcript(
    source: str | Path,
    *,
    whisper_fallback: bool = False,
    language: str | None = None,
    work_dir: Path | None = None,
) -> list[TranscriptSegment]:
    """取带时间戳的转写:URL 先试原生字幕,失败/本地文件走 Whisper 兜底。

    Args:
        source: URL 或本地音/视频路径。
        whisper_fallback: 字幕不可得时是否走 faster-whisper(下载/转写较慢)。
        language: 兜底转写语言(如 "zh")。
        work_dir: 字幕/临时文件落地目录(默认 source 所在目录)。

    Returns:
        时间戳分段列表(空 = 无字幕且未启用/未成功兜底)。
    """
    from hevi.ingest.video_fetch import is_url

    src = str(source)

    # 本地文件:直接走 Whisper(若允许),或提示
    if not is_url(src):
        p = Path(source)
        if not p.exists():
            raise TranscriptError(f"file not found: {p}")
        if whisper_fallback:
            return _whisper_transcribe(p, language=language)
        raise TranscriptError(
            f"no native captions for local file {p}; 需要 whisper_fallback=True 走转写"
        )

    # URL:先试 yt-dlp 字幕
    try:
        segs = _subs_via_ytdlp(src, work_dir)
        if segs:
            return segs
    except TranscriptError as e:
        logger_warn = f"(yt-dlp 字幕失败: {e})"
        if not whisper_fallback:
            raise TranscriptError(f"no captions via yt-dlp {logger_warn}") from e

    if whisper_fallback:
        from hevi.ingest.video_fetch import fetch_video

        work = work_dir or Path.cwd() / ".ingest_tmp"
        video = fetch_video(src, work)
        return _whisper_transcribe(video, language=language)
    return []


def _subs_via_ytdlp(url: str, work_dir: Path | None) -> list[TranscriptSegment]:
    """用 yt-dlp 拉原生字幕(manual/auto),不下载视频。"""
    import shutil
    import subprocess

    if shutil.which("yt-dlp") is None:
        raise TranscriptError("yt-dlp 未安装(URL 字幕需要它)")
    work = work_dir or Path.cwd() / ".ingest_tmp"
    work.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "yt-dlp",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "all",
            "--sub-format",
            "vtt/srt/best",
            "-o",
            str(work / "sub.%(ext)s"),
            url,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise TranscriptError(f"yt-dlp subs failed ({proc.returncode})")
    subs = sorted(
        p for p in work.glob("sub.*") if p.suffix.lower() in {".vtt", ".srt"}
    )
    if not subs:
        return []
    # 优先手写字幕(manual),其次 auto;文件名含字幕语言,取第一个可用即可
    segs: list[TranscriptSegment] = []
    for sub in subs:
        segs = read_subtitle_file(sub)
        if segs:
            return segs
    return []
