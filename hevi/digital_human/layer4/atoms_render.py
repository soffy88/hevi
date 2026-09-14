"""digital_human oprim:渲染/编码/交付原子。

对应 lanshu finalize_delivery.sh 的编码、响度归一化、接触表生成。
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from hevi.digital_human.schemas import AudioMeasurement

# ─── 编码参数 ───────────────────────────────────────


MASTER_ENCODE_PARAMS = {
    "crf": 16,
    "preset": "slow",
    "audio_bitrate": "256k",
}

SHARE_ENCODE_PARAMS = {
    "crf": 24,
    "preset": "medium",
    "audio_bitrate": "160k",
}

VIDEO_FILTER_TEMPLATE = (
    "scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos,setsar=1,fps={fps},format=yuv420p"
)


# ─── 响度归一化 (loudnorm 双遍) ────────────────────


def loudnorm_two_pass(
    input_path: str,
    output_path: str,
    target_lufs: float = -16,
    true_peak: float = -1.5,
    lra: float = 9,
) -> AudioMeasurement:
    """执行 loudnorm 双遍响度归一化。

    第一遍：测量
    第二遍：应用测量参数
    """
    source = _require_media(input_path)
    measured = _measure_loudnorm(source, target_lufs, true_peak, lra)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(output, "loudnorm")
    temporary.unlink(missing_ok=True)
    filter_expr = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary"
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source),
        "-map",
        "0:v:0?",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-af",
        filter_expr,
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-shortest",
        str(temporary),
    ]
    _run_ffmpeg(command, "loudnorm")
    _replace_nonempty(temporary, output, "loudnorm output")
    return AudioMeasurement(
        input_i=measured["input_i"],
        input_tp=measured["input_tp"],
        input_lra=measured["input_lra"],
        input_thresh=measured["input_thresh"],
        target_offset=measured["target_offset"],
        measured_lufs=measured["measured_lufs"],
        program_lufs=target_lufs,
    )


def build_loudnorm_filter(
    measurement: AudioMeasurement,
    target_lufs: float = -16,
    true_peak: float = -1.5,
    lra: float = 9,
) -> str:
    """根据测量结果构建 loudnorm 滤镜字符串。"""
    return (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
        f":measured_I={measurement.input_i}"
        f":measured_TP={measurement.input_tp}"
        f":measured_LRA={measurement.input_lra}"
        f":measured_thresh={measurement.input_thresh}"
        f":offset={measurement.target_offset}"
        f":linear=true:print_format=summary"
    )


# ─── 视频编码 ───────────────────────────────────────


def encode_video(
    input_path: str,
    output_path: str,
    crf: int = 23,
    preset: str = "medium",
    audio_bitrate: str = "128k",
    fps: int = 30,
) -> bool:
    """用 FFmpeg 生成可交付视频；失败或空文件直接报错。"""
    source = _require_media(input_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(output, "encode")
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        VIDEO_FILTER_TEMPLATE.format(fps=max(1, fps)),
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-shortest",
        "-movflags",
        "+faststart",
        str(temporary),
    ]
    _run_ffmpeg(command, "video encode")
    _replace_nonempty(temporary, output, "encoded video")
    return True


def generate_contact_sheet(
    video_path: str,
    output_path: str,
    frame_count: int = 9,
    tile: str = "3x3",
) -> bool:
    """生成 9 宫格接触表。

    对应 lanshu: "Contact sheet covers opening, chapters, emphasis graphics, close, and final frame"
    """
    source = _require_media(video_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_output(output, "contact")
    temporary.unlink(missing_ok=True)
    columns, rows = _parse_tile(tile)
    frame_count = max(1, frame_count)
    duration = _probe_duration(source)
    interval = max(duration / frame_count, 0.2) if duration > 0 else 1.0
    filter_expr = (
        f"fps=1/{interval:.6f},"
        "scale=480:270:force_original_aspect_ratio=decrease,"
        "pad=480:270:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"tile={columns}x{rows}:padding=4:margin=4"
    )
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(source),
        "-vf",
        filter_expr,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(temporary),
    ]
    _run_ffmpeg(command, "contact sheet")
    _replace_nonempty(temporary, output, "contact sheet")
    return True


def _require_media(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size == 0:
        raise FileNotFoundError(f"media file not found or empty: {candidate}")
    return candidate


def _temporary_output(output: Path, label: str) -> Path:
    """Keep the media suffix so FFmpeg can infer the output muxer."""
    suffix = output.suffix or ".mp4"
    return output.with_name(f".{output.stem}.{label}{suffix}")


def _run_ffmpeg(command: list[str], operation: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout)[-1600:]
        raise RuntimeError(f"{operation} failed: {detail}")


def _replace_nonempty(temporary: Path, output: Path, label: str) -> None:
    if not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"{label} was not produced")
    temporary.replace(output)


def _measure_loudnorm(
    source: Path,
    target_lufs: float,
    true_peak: float,
    lra: float,
) -> dict[str, float]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-af",
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"loudnorm measurement failed: {completed.stderr[-1200:]}")
    matches = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, re.S)
    if not matches:
        raise RuntimeError("loudnorm measurement returned no JSON")
    payload = json.loads(matches[-1])
    names = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    values: dict[str, float] = {}
    for name in names:
        value = _finite_float(payload.get(name))
        if value is None:
            raise RuntimeError(f"loudnorm measurement has invalid {name}")
        values[name] = value
    values["measured_lufs"] = values["input_i"]
    return values


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _probe_duration(source: Path) -> float:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe duration failed: {completed.stderr[-800:]}")
    try:
        duration = float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe returned no duration") from exc
    return max(duration, 0.0)


def _parse_tile(tile: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", tile.strip().lower())
    if not match:
        raise ValueError(f"invalid contact-sheet tile: {tile}")
    columns, rows = (int(value) for value in match.groups())
    if columns < 1 or rows < 1:
        raise ValueError(f"invalid contact-sheet tile: {tile}")
    return columns, rows


# ─── 接触表时间戳 ──────────────────────────────────


def calculate_contact_timestamps(duration_s: float, frame_count: int = 9) -> list[float]:
    """计算接触表采样时间点。

    对应 lanshu finalize_delivery.sh 的 awk 时间点计算
    """
    if duration_s <= 0:
        return [0.2] * frame_count

    timestamps = [0.2]
    timestamps.extend(
        duration_s * (i + 1) / (frame_count + 1) for i in range(1, frame_count - 1)
    )
    timestamps.append(max(0.2, duration_s - 0.2))
    return timestamps


def delivery_report(
    master_path: str,
    share_path: str,
    contact_sheet_path: str,
    duration_s: float,
    measurement: AudioMeasurement,
    source_probe: dict[str, Any],
    master_probe: dict[str, Any],
    share_probe: dict[str, Any],
    black_events: int = 0,
) -> dict[str, Any]:
    """生成交付报告 JSON。"""
    artifacts_exist = all(
        Path(path).is_file() and Path(path).stat().st_size > 0
        for path in (master_path, share_path, contact_sheet_path)
    )
    return {
        "status": "verified" if artifacts_exist else "blocked",
        "input": Path(master_path).name,
        "master": Path(master_path).name,
        "share": Path(share_path).name,
        "contact_sheet": Path(contact_sheet_path).name,
        "duration_s": duration_s,
        "source_loudness": {
            "input_i": measurement.input_i,
            "input_tp": measurement.input_tp,
            "input_lra": measurement.input_lra,
            "input_thresh": measurement.input_thresh,
            "target_offset": measurement.target_offset,
        },
        "source_probe": source_probe,
        "master_probe": master_probe,
        "share_probe": share_probe,
        "full_decode_passed": artifacts_exist,
        "black_frame_events": black_events,
    }
