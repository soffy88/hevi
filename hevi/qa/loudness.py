"""Two-pass EBU R128 normalisation for every finished video.

Product rule (S13): every delivered film is mastered to -14 LUFS integrated
with a -1.5 dBTP ceiling.  The measurement pass uses ffmpeg's ``loudnorm``
JSON output; the apply pass feeds those measured values back so the target is
reached in one encode instead of the drifting single-pass estimate.

The helper is deliberately conservative: a missing ffmpeg, a missing audio
stream, an unreadable file or a non-finite measurement is reported and the
video is left untouched.  It never invents audio and never fails a render.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LUFS_TARGET = -14.0
TRUE_PEAK_CEILING = -1.5
LOUDNESS_RANGE = 11.0


def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _has_audio(ffmpeg: str, path: Path) -> bool:
    if shutil.which("ffprobe") is None:
        return True
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(path),
            ],
            text=True,
            timeout=20,
            stderr=subprocess.DEVNULL,
        )
        return "audio" in out.lower()
    except (OSError, subprocess.SubprocessError):
        return True


def _json_block(text: str) -> dict[str, Any] | None:
    """Extract the last ``{...}`` JSON object ffmpeg printed for loudnorm."""
    for match in reversed(list(re.finditer(r"\{[^{}]*\}", text, re.S))):
        try:
            body = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and "input_i" in body:
            return body
    return None


def _finite(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def measure_loudness(path: Path) -> dict[str, Any]:
    """Measure integrated loudness and true peak with ffmpeg loudnorm."""
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        return {"measured": False, "reason": "ffmpeg not found"}
    target = os.environ.get("HEVI_LOUDNESS_TARGET", str(LUFS_TARGET))
    tp = os.environ.get("HEVI_LOUDNESS_TRUE_PEAK", str(TRUE_PEAK_CEILING))
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                f"loudnorm=I={target}:TP={tp}:LRA={LOUDNESS_RANGE:g}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"measured": False, "reason": f"measure failed: {type(exc).__name__}: {exc}"}
    body = _json_block((proc.stderr or "") + (proc.stdout or ""))
    if body is None:
        return {"measured": False, "reason": "loudnorm measurement output not found"}
    if _finite(body.get("input_i")) is None or _finite(body.get("input_tp")) is None:
        return {"measured": False, "reason": "loudnorm measurement incomplete"}
    return {"measured": True, **body}


def normalize_video_loudness(
    path: str | Path,
    *,
    target: float | None = None,
    true_peak: float | None = None,
) -> dict[str, Any]:
    """Normalise one finished video in place (two-pass, video stream copied)."""
    video = Path(path)
    evidence: dict[str, Any] = {"path": str(video), "normalized": False}
    ffmpeg = _ffmpeg()
    if ffmpeg is None:
        return {**evidence, "reason": "ffmpeg not found"}
    if not video.is_file() or video.stat().st_size == 0:
        return {**evidence, "reason": "missing or empty file"}
    if not _has_audio(ffmpeg, video):
        return {**evidence, "reason": "no audio stream"}

    target_i = float(os.environ.get("HEVI_LOUDNESS_TARGET", target if target is not None else LUFS_TARGET))
    target_tp = float(
        os.environ.get("HEVI_LOUDNESS_TRUE_PEAK", true_peak if true_peak is not None else TRUE_PEAK_CEILING)
    )
    measured = measure_loudness(video)
    evidence["measurement"] = measured
    if not measured.get("measured"):
        return {**evidence, "reason": str(measured.get("reason") or "not measured")}

    tmp = video.with_name(f".{video.stem}.loudnorm{video.suffix}")
    applied_filter = (
        f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA={LOUDNESS_RANGE:g}:"
        f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
        f"measured_LRA={measured.get('input_lra', '0')}:"
        f"measured_thresh={measured.get('input_thresh', '-70')}:"
        f"offset={measured.get('target_offset', '0')}:linear=true"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(video),
        "-map",
        "0:v?",
        "-map",
        "0:a",
        "-c:v",
        "copy",
        "-af",
        applied_filter,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        tmp.unlink(missing_ok=True)
        return {**evidence, "reason": f"apply failed: {type(exc).__name__}: {exc}"}
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        # A linear two-pass apply can be rejected for very short or clipped
        # sources; fall back to the single-pass filter rather than leave the
        # film at the wrong level.
        fallback = [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-map",
            "0:v?",
            "-map",
            "0:a",
            "-c:v",
            "copy",
            "-af",
            f"loudnorm=I={target_i:g}:TP={target_tp:g}:LRA={LOUDNESS_RANGE:g}",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        try:
            proc = subprocess.run(fallback, capture_output=True, text=True, timeout=300, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            tmp.unlink(missing_ok=True)
            return {**evidence, "reason": f"apply failed: {type(exc).__name__}: {exc}"}
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return {**evidence, "reason": "loudnorm apply produced no file"}
        evidence["mode"] = "single-pass-fallback"
    else:
        evidence["mode"] = "two-pass"
    os.replace(tmp, video)
    after = measure_loudness(video)
    evidence.update(
        {
            "normalized": True,
            "target_lufs": target_i,
            "true_peak_ceiling_db": target_tp,
            "measured_input_i": measured.get("input_i"),
            "measured_input_tp": measured.get("input_tp"),
            "after": after if after.get("measured") else None,
        }
    )
    return evidence


__all__ = [
    "LUFS_TARGET",
    "TRUE_PEAK_CEILING",
    "measure_loudness",
    "normalize_video_loudness",
]
