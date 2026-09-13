"""Single media validation gate used by every production qualification.

The validator is deliberately conservative: a missing or unprobeable artifact
is a failure, never a warning or an implicit success.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MediaValidation:
    path: str
    exists: bool
    nonzero: bool
    ffprobe_valid: bool
    duration_s: float | None
    video_stream: bool
    audio_stream: bool
    codec: str | None
    width: int | None
    height: int | None
    fps: float | None
    errors: list[str] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fps(stream: dict[str, Any]) -> float | None:
    raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not raw or raw == "0/0":
        return None
    try:
        numerator, denominator = str(raw).split("/", 1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None


def validate_media(path: str | Path, *, require_audio: bool = False) -> MediaValidation:
    """Validate a final media artifact with ffprobe and strict basic invariants."""

    target = Path(path)
    exists = target.is_file()
    nonzero = exists and target.stat().st_size > 0
    errors: list[str] = []
    if not exists:
        errors.append("artifact_missing")
    elif not nonzero:
        errors.append("artifact_empty")
    if shutil.which("ffprobe") is None:
        errors.append("ffprobe_unavailable")
        return MediaValidation(
            str(target), exists, nonzero, False, None, False, False, None,
            None, None, None, errors, False,
        )
    if not exists or not nonzero:
        return MediaValidation(
            str(target), exists, nonzero, False, None, False, False, None,
            None, None, None, errors, False,
        )
    command = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(target),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if completed.returncode != 0:
            errors.append("ffprobe_parse_failed")
            return MediaValidation(
                str(target), True, True, False, None, False, False, None,
                None, None, None, errors, False,
            )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        errors.append("ffprobe_parse_failed")
        return MediaValidation(
            str(target), True, True, False, None, False, False, None,
            None, None, None, errors, False,
        )
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    fmt = payload.get("format", {})
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        errors.append("duration_invalid")
    if video is None:
        errors.append("video_stream_missing")
    if require_audio and audio is None:
        errors.append("audio_stream_missing")
    return MediaValidation(
        path=str(target), exists=True, nonzero=True, ffprobe_valid=True,
        duration_s=duration, video_stream=video is not None, audio_stream=audio is not None,
        codec=(video or {}).get("codec_name"), width=(video or {}).get("width"),
        height=(video or {}).get("height"), fps=_fps(video or {}), errors=errors,
        passed=not errors,
    )
