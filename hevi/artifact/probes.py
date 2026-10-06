"""HEVI P8.4 — Observation. The probe reads bytes and reports what it sees.

Two rules govern this module.

**Observation only.** A probe reads and measures. It never writes, repairs, remuxes or
otherwise touches the artifact. A validator that can modify what it validates is not a
validator, and ``test_probe_module_cannot_write`` holds the line on the AST — no
``open``, no ``write``, no ``unlink``, no ``Path``.

**No filesystem.** Probes take **bytes**. P8.3 established that a receipt may not be
issued from a path, because ``artifact_exists() != production_success``; the same
reasoning applies here, where a path would additionally allow a validator to repair
the file it is inspecting. ffprobe reads from ``pipe:0`` for exactly this reason, so a
real video can be qualified without ever touching a file.

There is an existing media-inspection authority — ``hevi.video.quality_check.probe_stats``
— which shells out to ffprobe per stream against a path. It is not duplicated here.
What is added is the byte-oriented seam the rest of P8 needs, plus image format
detection by magic number, which ffprobe is not needed for.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from typing import Any, Protocol

from hevi.evidence.acquisition import checksum_bytes

#: Observations a probe may report. A closed vocabulary, so a typo in a check name is
#: an error rather than a check that silently never runs.
OBSERVABLE_FIELDS = frozenset(
    {"checksum", "container", "codec", "width", "height", "resolution", "duration",
     "fps", "sample_rate", "channels", "format", "size_bytes", "has_audio"}
)


class ArtifactProbe(Protocol):
    """Reports what it observes about a payload. Never alters it."""

    def __call__(self, payload: bytes) -> dict[str, Any]: ...


# ── image formats, by magic number ───────────────────────────────────────
# ffprobe is not needed to know a PNG is a PNG, and reading four bytes is a far more
# reliable observation than trusting a filename extension.

_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)


def detect_image_format(payload: bytes) -> str | None:
    """The image format by signature, or ``None`` if unrecognised."""
    for magic, name in _IMAGE_MAGIC:
        if payload.startswith(magic):
            if name == "webp":
                return name
            return name
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "webp"
    return None


def probe_image(payload: bytes) -> dict[str, Any]:
    """Observe an image from its bytes."""
    fmt = detect_image_format(payload)
    observed: dict[str, Any] = {
        "checksum": checksum_bytes(payload),
        "size_bytes": len(payload),
    }
    if fmt is not None:
        observed["format"] = fmt
    return observed


# ── containerised media, via ffprobe over a pipe ──────────────────────────


def detect_container(payload: bytes) -> str | None:
    """The ISO base media container format, which declares itself in its header."""
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        return payload[8:12].decode("ascii", "replace").strip()
    if payload[:4] in (b"RIFF",) and payload[8:12] in (b"WAVE", b"AVI "):
        return {b"WAVE": "wav", b"AVI ": "avi"}[payload[8:12]]
    if payload[:3] == b"\xff\xfb" or payload[:2] in (b"ID", b"MP"):
        return "mp3"
    return None


def ffprobe_payload(payload: bytes, *, timeout_s: float = 10.0) -> dict[str, Any] | None:
    """Ask ffprobe what is in these bytes, without writing them anywhere.

    Returns ``None`` when ffprobe is unavailable or cannot read the payload, which the
    caller must treat as *not observed* rather than as a failed check.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "format=duration,format_name",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
                "-of", "json",
                "pipe:0",
            ],
            input=payload,
            capture_output=True,
            timeout=timeout_s,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed
    except json.JSONDecodeError:
        return None


def _parse_rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        try:
            return float(value) if value else None
        except ValueError:
            return None
    num, _, den = value.partition("/")
    try:
        numerator, denominator = float(num), float(den)
    except ValueError:
        return None
    return numerator / denominator if denominator else None


def probe_containerised(payload: bytes) -> dict[str, Any]:
    """Observe video/audio metadata from bytes via ffprobe.

    Every field is optional: a missing stream yields ``None``, which makes dependent
    checks report *not observed* rather than passing on a default.
    """
    observed: dict[str, Any] = {
        "checksum": checksum_bytes(payload),
        "size_bytes": len(payload),
    }
    container = detect_container(payload)
    if container is not None:
        observed["container"] = container

    parsed = ffprobe_payload(payload)
    if parsed is None:
        return observed

    fmt = parsed.get("format") or {}
    duration = fmt.get("duration")
    if duration is not None:
        with contextlib.suppress(TypeError, ValueError):
            observed["duration"] = float(duration)

    for stream in parsed.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and "codec" not in observed:
            observed["codec"] = stream.get("codec_name")
            if stream.get("width") and stream.get("height"):
                observed["width"] = int(stream["width"])
                observed["height"] = int(stream["height"])
                observed["resolution"] = (int(stream["width"]), int(stream["height"]))
            fps = _parse_rate(stream.get("r_frame_rate"))
            if fps:
                observed["fps"] = fps
            observed["has_audio"] = False
        elif kind == "audio" and "sample_rate" not in observed:
            observed["codec"] = observed.get("codec") or stream.get("codec_name")
            if stream.get("sample_rate"):
                observed["sample_rate"] = int(stream["sample_rate"])
            if stream.get("channels"):
                observed["channels"] = int(stream["channels"])
            observed["has_audio"] = True
    return observed


__all__ = [
    "OBSERVABLE_FIELDS",
    "ArtifactProbe",
    "detect_container",
    "detect_image_format",
    "ffprobe_payload",
    "probe_containerised",
    "probe_image",
]
