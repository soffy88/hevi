"""ffmpeg / ffprobe plumbing for the enhancement primitives.

No media claim is ever made without a real probe or a real ffmpeg run; every
helper raises on failure so the caller can record ``status="failed"``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from hevi.layer4_legacy.enhance.oprim_impl.contracts import MediaInfo

#: Binary resolution mirrors hevi/layer4_legacy/talkcraft/omodul_impl/_media.py.
FFMPEG = os.environ.get("HEVI_FFMPEG") or shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = (
    os.environ.get("HEVI_FFPROBE") or shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"
)

_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})
_VIDEO_EXT = frozenset({".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"})
_AUDIO_EXT = frozenset({".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".opus"})


class MediaError(RuntimeError):
    """A media probe/encode could not be performed (never silently swallowed)."""


def media_kind(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _AUDIO_EXT:
        return "audio"
    return "unknown"


def run_ffmpeg(args: list[str], *, timeout_s: float = 1800.0) -> str:
    """Run ffmpeg with ``-hide_banner``; raise MediaError on non-zero exit."""
    cmd = [FFMPEG, "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise MediaError(f"ffmpeg failed (rc={proc.returncode}): {' | '.join(tail)}")
    return proc.stderr or ""


def probe_media(path: str | Path) -> MediaInfo:
    """Real ffprobe of ``path`` (format + streams). Raises if unreadable."""
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
            str(dest),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed: {(proc.stderr or '').strip()[:200]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    fps = 0.0
    if video and video.get("avg_frame_rate") and video["avg_frame_rate"] != "0/0":
        num, _, den = video["avg_frame_rate"].partition("/")
        try:
            fps = float(num) / float(den) if float(den) else 0.0
        except TypeError, ValueError, ZeroDivisionError:
            fps = 0.0

    duration = 0.0
    for source in (fmt.get("duration"), video.get("duration") if video else None):
        try:
            if source:
                duration = float(source)
                break
        except TypeError, ValueError:
            continue

    return MediaInfo(
        path=str(dest),
        kind=media_kind(dest),
        width=int(video.get("width") or 0) if video else 0,
        height=int(video.get("height") or 0) if video else 0,
        duration_s=round(duration, 3),
        fps=round(fps, 3),
        has_audio=has_audio,
        size_bytes=int(fmt.get("size") or dest.stat().st_size),
        codec=str(video.get("codec_name") or "") if video else "",
    )


def extract_frames(
    video: str | Path,
    out_dir: str | Path,
    *,
    count: int = 4,
    scale: int = 0,
) -> list[Path]:
    """Extract ``count`` evenly spaced frames (1-based, avoids first/last)."""
    src = Path(video)
    info = probe_media(src)
    if info.kind != "video" or info.duration_s <= 0:
        raise MediaError(f"cannot sample frames from non-video: {src}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for i in range(count):
        # evenly spaced, shifted off the exact boundaries
        t = info.duration_s * (i + 0.5) / count
        dest = out / f"frame_{i:02d}.png"
        vf = f"scale={scale}:-2" if scale else "null"
        run_ffmpeg(
            [
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(src),
                "-frames:v",
                "1",
                "-vf",
                vf,
                str(dest),
            ],
            timeout_s=300.0,
        )
        if not dest.is_file() or dest.stat().st_size == 0:
            raise MediaError(f"frame extraction produced nothing at {t:.3f}s")
        frames.append(dest)
    return frames


def video_to_frames(
    video: str | Path, out_dir: str | Path, *, limit: int = 0
) -> tuple[list[Path], float]:
    """Decode every frame of a video to PNG. Returns (frames, fps)."""
    src = Path(video)
    info = probe_media(src)
    if info.kind != "video":
        raise MediaError(f"not a video: {src}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    args = ["-y", "-i", str(src), "-vsync", "0", str(out / "f_%06d.png")]
    if limit > 0:
        args = ["-y", "-i", str(src), "-frames:v", str(limit), str(out / "f_%06d.png")]
    run_ffmpeg(args)
    frames = sorted(out.glob("f_*.png"))
    if not frames:
        raise MediaError(f"no frames decoded from {src}")
    return frames, info.fps or 24.0


def frames_to_video(
    frames: list[Path],
    out_path: str | Path,
    *,
    fps: float,
    audio_from: str | Path | None = None,
) -> Path:
    """Encode a PNG sequence back to H.264, optionally remuxing source audio."""
    if not frames:
        raise MediaError("frames_to_video called with no frames")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Stage a clean, gap-free %06d sequence (source names may be arbitrary).
    stage = out.parent / f".{out.stem}_seq"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    for i, frame in enumerate(frames):
        os.symlink(Path(frame).resolve(), stage / f"img_{i:06d}.png")
    pattern = str(stage / "img_%06d.png")
    args = ["-y", "-framerate", f"{fps:.4f}", "-i", pattern]
    if audio_from is not None:
        args += [
            "-i",
            str(audio_from),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0?",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
        ]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)]
    run_ffmpeg(args)
    shutil.rmtree(stage, ignore_errors=True)
    return out


__all__ = [
    "FFMPEG",
    "FFPROBE",
    "MediaError",
    "extract_frames",
    "frames_to_video",
    "media_kind",
    "probe_media",
    "run_ffmpeg",
    "video_to_frames",
]
