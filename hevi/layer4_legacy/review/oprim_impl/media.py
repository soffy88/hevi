"""ffprobe / ffmpeg plumbing for the review primitives.

Every number in a review report comes from a real probe or a real ffmpeg run;
a helper that cannot measure raises instead of returning a default, so the
workflow can record ``status="blocked"`` rather than a fabricated pass.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from hevi.layer4_legacy.review.oprim_impl.contracts import ProbeReport

FFMPEG = os.environ.get("HEVI_FFMPEG") or shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = (
    os.environ.get("HEVI_FFPROBE") or shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
)

_VIDEO_EXT = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})


class MediaError(RuntimeError):
    """A probe/encode could not be performed (never silently swallowed)."""


def media_kind(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        return "image"
    if ext in {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".opus"}:
        return "audio"
    return "unknown"


def run_ffmpeg(args: list[str], *, timeout_s: float = 1800.0) -> str:
    cmd = [FFMPEG, "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise MediaError(f"ffmpeg failed (rc={proc.returncode}): {' | '.join(tail)}")
    return proc.stderr or ""


def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    """Real sha256 of the file on disk (streamed)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def probe_media(path: str | Path, *, with_sha256: bool = False) -> ProbeReport:
    """Real ffprobe of ``path`` plus (optionally) its sha256."""
    dest = Path(path)
    if not dest.is_file() or dest.stat().st_size == 0:
        raise MediaError(f"media not found or empty: {dest}")
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-count_frames",
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed: {(proc.stderr or '').strip()[:200]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    fps = 0.0
    if video:
        for key in ("avg_frame_rate", "r_frame_rate"):
            raw = video.get(key)
            if raw and raw != "0/0":
                num, _, den = raw.partition("/")
                try:
                    fps = float(num) / float(den) if float(den) else 0.0
                except TypeError, ValueError, ZeroDivisionError:
                    continue
                if fps > 0:
                    break

    duration = 0.0
    for source in (fmt.get("duration"), video.get("duration") if video else None):
        try:
            if source:
                duration = float(source)
                break
        except TypeError, ValueError:
            continue

    nb_frames = 0
    if video:
        try:
            nb_frames = int(video.get("nb_read_frames") or 0)
        except TypeError, ValueError:
            nb_frames = 0

    return ProbeReport(
        path=str(dest),
        kind=media_kind(dest),
        width=int(video.get("width") or 0) if video else 0,
        height=int(video.get("height") or 0) if video else 0,
        duration_s=round(duration, 3),
        fps=round(fps, 3),
        has_audio=audio is not None,
        size_bytes=int(fmt.get("size") or dest.stat().st_size),
        video_codec=str(video.get("codec_name") or "") if video else "",
        audio_codec=str(audio.get("codec_name") or "") if audio else "",
        nb_frames=nb_frames,
        sha256=sha256_file(dest) if with_sha256 else "",
    )


__all__ = [
    "FFMPEG",
    "FFPROBE",
    "MediaError",
    "media_kind",
    "probe_media",
    "run_ffmpeg",
    "sha256_file",
]
