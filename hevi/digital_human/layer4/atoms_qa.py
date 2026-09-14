"""digital_human oprim:QA 验收原子。

对应 lanshu qa-recovery.md 的 acceptance gates。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from hevi.digital_human.schemas import PresenterJob

# ─── 授权检查 ──────────────────────────────────────


def check_authorization(job: PresenterJob) -> dict[str, Any]:
    """检查作业授权状态。

    对应 lanshu: "Confirm image rights, adult status, remote-upload permission"
    """
    return {
        "rights_confirmed": job.rights_confirmed,
        "adult_presenter_confirmed": job.adult_presenter_confirmed,
        "remote_upload_approved": job.remote_upload_approved,
        "voice_clone_approved": job.voice_clone_approved,
        "remote_ready": all([
            job.rights_confirmed,
            job.adult_presenter_confirmed,
            job.remote_upload_approved,
            job.voice_clone_approved,
        ]),
    }


# ─── 技术检查 ──────────────────────────────────────


def check_media_technical(job: PresenterJob) -> dict[str, Any]:
    """检查媒体技术指标。

    对应 lanshu preflight.py 的 ffprobe 检查
    """
    errors: list[str] = []
    warnings: list[str] = []
    media: dict[str, Any] = {}

    # 检查 presenter image
    if not job.presenter_image:
        errors.append("presenter_image is required")
    else:
        path = Path(job.presenter_image)
        if not path.is_file():
            errors.append(f"presenter_image not found: {job.presenter_image}")
        else:
            try:
                probe_result = _ffprobe(path)
                if not probe_result:
                    errors.append("presenter image has no decodable stream")
                else:
                    w = int(probe_result.get("width", 0) or 0)
                    h = int(probe_result.get("height", 0) or 0)
                    if min(w, h) < 512:
                        warnings.append(f"presenter image low resolution: {w}x{h}")
                    media["presenter_image"] = probe_result
            except Exception as exc:
                errors.append(f"cannot decode presenter image: {exc}")

    # 检查声音样本
    if job.voice_sample:
        path = Path(job.voice_sample)
        if not path.is_file():
            errors.append(f"voice_sample not found: {job.voice_sample}")
        else:
            try:
                probe_result = _ffprobe(path)
                streams = [s for s in probe_result.get("streams", []) if s.get("codec_type") == "audio"]
                if not streams:
                    errors.append("voice sample has no audio stream")
                duration = float(probe_result.get("duration", 0) or 0)
                if duration < 4:
                    warnings.append(f"voice sample is short: {duration:.1f}s")
                if duration > 60:
                    warnings.append(f"voice sample is long: {duration:.1f}s")
                media["voice_sample"] = probe_result
            except Exception as exc:
                errors.append(f"cannot decode voice sample: {exc}")
    else:
        warnings.append("no voice sample; will use stock voice")

    # 检查 supporting media
    for item in job.supporting_media:
        path = Path(item)
        if not path.is_file():
            warnings.append(f"supporting media not found: {item}")

    return {"errors": errors, "warnings": warnings, "media": media}


def check_audio_loudness(audio_path: str, target_lufs: float = -16) -> dict[str, Any]:
    """检查音频响度是否达标。

    对应 lanshu: "Assembled program loudness commonly -16 ± 0.5 LUFS"
    """
    path = Path(audio_path)
    if not path.is_file():
        return {"ok": False, "error": f"audio file not found: {audio_path}"}

    try:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=9:print_format=json",
            "-f",
            "null",
            "-",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return {
                "ok": False,
                "error": completed.stderr[-1200:] or "ffmpeg loudness probe failed",
            }
        matches = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, re.S)
        if not matches:
            return {"ok": False, "error": "ffmpeg loudnorm returned no measurement"}
        payload = json.loads(matches[-1])
        measured = _finite_float(payload.get("input_i"))
        if measured is None:
            return {"ok": False, "error": f"invalid loudness value: {payload.get('input_i')}"}
        deviation = measured - target_lufs
        return {
            "ok": True,
            "measured_lufs": measured,
            "target_lufs": target_lufs,
            "deviation": deviation,
            "in_spec": abs(deviation) <= 0.5,
            "input_tp": _finite_float(payload.get("input_tp")),
            "input_lra": _finite_float(payload.get("input_lra")),
            "input_thresh": _finite_float(payload.get("input_thresh")),
            "target_offset": _finite_float(payload.get("target_offset")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _ffprobe(path: Path) -> dict[str, Any]:
    """用 ffprobe 读取真实媒体流信息；不可解码时抛错。"""
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=index,codec_type,codec_name,width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-1000:] or "ffprobe failed")
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError("media has no decodable streams")
    result: dict[str, Any] = {
        "path": str(path),
        "format": payload.get("format", {}).get("format_name", ""),
        "streams": streams,
    }
    duration = _finite_float(payload.get("format", {}).get("duration"))
    if duration is not None:
        result["duration"] = duration
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video:
        result["width"] = int(video.get("width") or 0)
        result["height"] = int(video.get("height") or 0)
        result["video_codec"] = video.get("codec_name", "")
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio:
        result["audio_codec"] = audio.get("codec_name", "")
    return result


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None
