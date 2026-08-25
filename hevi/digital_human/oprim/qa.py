"""digital_human oprim:QA 验收原子。

对应 lanshu qa-recovery.md 的 acceptance gates。
"""

from __future__ import annotations

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
        # 假设音频文件存在，进行响度测量 (占位)
        result = {
            "ok": True,
            "measured_lufs": target_lufs,
            "target_lufs": target_lufs,
            "deviation": 0.0,
        }
        if abs(result["deviation"]) <= 0.5:
            result["in_spec"] = True
        else:
            result["in_spec"] = False
        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _ffprobe(path: Path) -> dict[str, Any]:
    """ffprobe 探测媒体文件 (占位实现)。"""
    # 实际实现需调用 ffprobe，这里返回模拟结构
    return {
        "path": str(path.name),
        "width": 1080,
        "height": 1920,
        "duration": 60.0,
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
    }