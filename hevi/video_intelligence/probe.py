"""Machine-only video probing through ffprobe."""

from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import suppress
from pathlib import Path

from .models import SourceType, VideoAsset, VideoProbe


class VideoProbeError(RuntimeError):
    """The input is not a readable video."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: str | Path, *, asset_id: str | None = None) -> VideoProbe:
    target = Path(path)
    if not target.is_file() or target.stat().st_size == 0:
        raise VideoProbeError(f"VIDEO_NOT_FOUND:{target}")
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VideoProbeError(f"FFPROBE_FAILED:{exc}") from exc
    if completed.returncode != 0:
        raise VideoProbeError(f"FFPROBE_FAILED:{completed.stderr.strip()[:300]}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VideoProbeError("FFPROBE_FAILED:invalid_json") from exc
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None:
        raise VideoProbeError("VIDEO_UNREADABLE:video_stream_missing")
    fmt = payload.get("format", {})
    try:
        duration_ms = round(float(fmt["duration"]) * 1000)
    except (KeyError, TypeError, ValueError) as exc:
        raise VideoProbeError("FFPROBE_FAILED:duration_missing") from exc
    raw_rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
    fps_num: int | None = None
    fps_den: int | None = None
    if "/" in raw_rate:
        left, right = raw_rate.split("/", 1)
        with suppress(ValueError):
            fps_num, fps_den = int(left), int(right)
    def _int(value: object) -> int | None:
        try:
            return int(str(value)) if value is not None else None
        except (TypeError, ValueError):
            return None
    return VideoProbe(
        asset_id=asset_id,
        path=str(target),
        duration_ms=duration_ms,
        fps_num=fps_num,
        fps_den=fps_den,
        frame_count=_int(video.get("nb_frames")),
        width=_int(video.get("width")),
        height=_int(video.get("height")),
        pixel_format=video.get("pix_fmt"),
        video_codec=video.get("codec_name"),
        audio_codec=(audio or {}).get("codec_name"),
        audio_sample_rate=_int((audio or {}).get("sample_rate")),
        audio_channels=_int((audio or {}).get("channels")),
        bitrate=_int(fmt.get("bit_rate")),
        container=fmt.get("format_name"),
        has_video=True,
        has_audio=audio is not None,
    )


def video_asset(path: str | Path, *, source_type: SourceType = SourceType.GENERATED) -> VideoAsset:
    target = Path(path)
    probe = probe_video(target)
    fps = None
    if probe.fps_num and probe.fps_den:
        fps = probe.fps_num / probe.fps_den
    return VideoAsset(
        asset_id=f"video:{_sha256(target)[:16]}",
        uri=str(target),
        local_path=str(target),
        sha256=_sha256(target),
        duration_s=probe.duration_ms / 1000,
        width=probe.width or 0,
        height=probe.height or 0,
        fps=fps,
        codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        source_type=source_type,
    )
