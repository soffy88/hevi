"""Video file qualification checks using ffmpeg and ffprobe (CPU-only, real frame extraction).

Performs deterministic video QA on delivered MP4 files:
1. Aspect ratio check (9:16 target with parameterized tolerance).
2. Flicker detection (adjacent frame brightness jump frequency & jump ratio).
3. First-last frame similarity for seamless looping.
All thresholds are fully parameterized.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import numpy as np


def _find_binary(name: str) -> str:
    """Find path to executable or fallback to common local bin paths."""
    found = shutil.which(name)
    if found:
        return found
    common_paths = [
        Path("/home/soffy/.local/bin") / name,
        Path("/usr/local/bin") / name,
        Path("/usr/bin") / name,
    ]
    for p in common_paths:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    return name


FFMPEG_BIN = _find_binary("ffmpeg")
FFPROBE_BIN = _find_binary("ffprobe")


@dataclass(frozen=True)
class AspectCheckResult:
    ok: bool
    width: int
    height: int
    aspect_ratio: float
    target_aspect: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FlickerCheckResult:
    ok: bool
    jump_count: int
    total_frames: int
    duration: float
    flicker_frequency: float  # jumps per second
    flicker_ratio: float      # jumps / (total_frames - 1)
    max_brightness_diff: float
    mean_brightness_diff: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LoopCheckResult:
    ok: bool
    similarity: float  # 0.0 to 1.0 (1.0 = identical)
    mean_abs_diff: float  # 0.0 to 1.0
    threshold: float
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoCheckReport:
    ok: bool
    video_path: str
    aspect: AspectCheckResult
    flicker: FlickerCheckResult
    loop: LoopCheckResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "video_path": self.video_path,
            "aspect": self.aspect.to_dict(),
            "flicker": self.flicker.to_dict(),
            "loop": self.loop.to_dict() if self.loop is not None else None,
        }

    def format_text(self) -> str:
        status = "PASS (质检合格)" if self.ok else "FAIL (质检不合格)"
        lines = [
            f"=== Video QA Check Report: {status} ===",
            f"视频文件: {self.video_path}",
            f"1. 宽高比检查: {'[PASS]' if self.aspect.ok else '[FAIL]'} {self.aspect.message}",
            f"2. 闪烁检测:   {'[PASS]' if self.flicker.ok else '[FAIL]'} {self.flicker.message}",
        ]
        if self.loop is not None:
            lines.append(f"3. 循环首尾帧: {'[PASS]' if self.loop.ok else '[FAIL]'} {self.loop.message}")
        return "\n".join(lines)


def get_video_metadata(video_path: str | Path) -> dict[str, Any]:
    """Extract video dimensions, duration and fps using ffprobe."""
    path_str = str(video_path)
    cmd = [
        FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,r_frame_rate,nb_frames",
        "-show_entries", "format=duration",
        "-of", "json",
        path_str,
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"No video streams found in {path_str}")

    stream = streams[0]
    width = int(stream.get("width", 0))
    height = int(stream.get("height", 0))

    # Duration fallback from stream or format
    duration_str = stream.get("duration") or data.get("format", {}).get("duration", "0")
    duration = float(duration_str)

    # Frame rate
    r_frame_rate = stream.get("r_frame_rate", "25/1")
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 25.0
    else:
        fps = float(r_frame_rate)

    return {
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
    }


def check_aspect_ratio(
    video_path: str | Path,
    target_ratio: tuple[int, int] = (9, 16),
    tolerance: float = 0.02,
) -> AspectCheckResult:
    """Verify video aspect ratio against target (default 9:16 portrait)."""
    meta = get_video_metadata(video_path)
    w, h = meta["width"], meta["height"]
    if h == 0:
        return AspectCheckResult(
            ok=False,
            width=w,
            height=h,
            aspect_ratio=0.0,
            target_aspect=target_ratio[0] / target_ratio[1],
            message=f"无效视频高度: h={h}",
        )

    aspect = w / h
    target = target_ratio[0] / target_ratio[1]
    rel_diff = abs(aspect - target) / target
    ok = rel_diff <= tolerance

    if ok:
        msg = f"尺寸 {w}x{h} (比例 {aspect:.4f}) 符合 {target_ratio[0]}:{target_ratio[1]} (目标 {target:.4f}, 相对误差 {rel_diff:.2%})"
    else:
        msg = f"尺寸 {w}x{h} (比例 {aspect:.4f}) 不符合 {target_ratio[0]}:{target_ratio[1]} (目标 {target:.4f}, 相对误差 {rel_diff:.2%} > 容差 {tolerance:.2%})"

    return AspectCheckResult(
        ok=ok,
        width=w,
        height=h,
        aspect_ratio=aspect,
        target_aspect=target,
        message=msg,
    )


def check_flicker(
    video_path: str | Path,
    *,
    jump_threshold: float = 20.0,
    max_flicker_frequency: float = 2.0,
    max_flicker_ratio: float = 0.05,
) -> FlickerCheckResult:
    """Detect brightness flicker by analyzing adjacent frame luminance jumps.

    Parameters:
    - jump_threshold: Minimum brightness difference (0-255 scale) between adjacent frames to count as jump.
    - max_flicker_frequency: Maximum allowed jump events per second before flagging failure.
    - max_flicker_ratio: Maximum allowed jump count / total transitions before flagging failure.
    """
    path_str = str(video_path)
    meta = get_video_metadata(path_str)
    duration = meta["duration"]

    # Extract 64x64 gray frames via ffmpeg pipe
    cmd = [
        FFMPEG_BIN,
        "-i", path_str,
        "-vf", "scale=64:64,format=gray",
        "-f", "rawvideo",
        "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    raw = proc.stdout
    frame_size = 64 * 64
    total_frames = len(raw) // frame_size

    if total_frames < 2:
        return FlickerCheckResult(
            ok=True,
            jump_count=0,
            total_frames=total_frames,
            duration=duration,
            flicker_frequency=0.0,
            flicker_ratio=0.0,
            max_brightness_diff=0.0,
            mean_brightness_diff=0.0,
            message=f"视频帧数不足以进行差分分析 (frames={total_frames})",
        )

    frames = np.frombuffer(raw[:total_frames * frame_size], dtype=np.uint8).reshape((-1, 64, 64))
    # Frame mean luminance (0.0 - 255.0)
    luminance = frames.mean(axis=(1, 2))
    diffs = np.abs(np.diff(luminance))

    jumps = int(np.sum(diffs > jump_threshold))
    max_diff = float(np.max(diffs))
    mean_diff = float(np.mean(diffs))

    effective_dur = duration if duration > 0.0 else (total_frames / meta["fps"])
    flicker_freq = jumps / effective_dur if effective_dur > 0.0 else 0.0
    flicker_ratio = jumps / (total_frames - 1)

    ok = (flicker_freq <= max_flicker_frequency) and (flicker_ratio <= max_flicker_ratio)

    if ok:
        msg = (
            f"未检测到异常频闪 (跳变次数: {jumps}, 跳变频率: {flicker_freq:.2f}次/秒 <= 阈值 {max_flicker_frequency}, "
            f"跳变占比: {flicker_ratio:.1%}, 平均相邻帧亮度差: {mean_diff:.2f}, 最大差: {max_diff:.2f})"
        )
    else:
        msg = (
            f"检测到明显画面频闪 (跳变次数: {jumps}, 跳变频率: {flicker_freq:.2f}次/秒 > 阈值 {max_flicker_frequency}, "
            f"跳变占比: {flicker_ratio:.1%} > {max_flicker_ratio:.1%}, 最大相邻帧亮度差: {max_diff:.2f})"
        )

    return FlickerCheckResult(
        ok=ok,
        jump_count=jumps,
        total_frames=total_frames,
        duration=effective_dur,
        flicker_frequency=flicker_freq,
        flicker_ratio=flicker_ratio,
        max_brightness_diff=max_diff,
        mean_brightness_diff=mean_diff,
        message=msg,
    )


def check_loop_similarity(
    video_path: str | Path,
    similarity_threshold: float = 0.95,
) -> LoopCheckResult:
    """Check similarity between first and last video frames to verify seamless loop.

    Extracts first and last frame at 128x128 RGB, computes normalized mean absolute error.
    similarity = 1.0 - mean_abs_diff.
    """
    path_str = str(video_path)
    # Extract all frames or first and last
    cmd = [
        FFMPEG_BIN,
        "-i", path_str,
        "-vf", "scale=128:128,format=rgb24",
        "-f", "rawvideo",
        "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    raw = proc.stdout
    frame_bytes = 128 * 128 * 3
    total_frames = len(raw) // frame_bytes

    if total_frames < 2:
        return LoopCheckResult(
            ok=False,
            similarity=0.0,
            mean_abs_diff=1.0,
            threshold=similarity_threshold,
            message="视频帧数过少，无法比对首尾帧",
        )

    frames = np.frombuffer(raw[:total_frames * frame_bytes], dtype=np.uint8).reshape((-1, 128, 128, 3))
    first_frame = frames[0].astype(np.float32)
    last_frame = frames[-1].astype(np.float32)

    mean_diff = float(np.mean(np.abs(first_frame - last_frame)) / 255.0)
    similarity = float(1.0 - mean_diff)
    ok = similarity >= similarity_threshold

    if ok:
        msg = f"首尾帧相似度 {similarity:.4f} (差异 {mean_diff:.4f}) >= 阈值 {similarity_threshold:.2f}，可无缝循环"
    else:
        msg = f"首尾帧相似度 {similarity:.4f} (差异 {mean_diff:.4f}) < 阈值 {similarity_threshold:.2f}，首尾存在明显跳跃无法平滑循环"

    return LoopCheckResult(
        ok=ok,
        similarity=similarity,
        mean_abs_diff=mean_diff,
        threshold=similarity_threshold,
        message=msg,
    )


def check_video(
    video_path: str | Path,
    *,
    is_loop: bool = False,
    target_aspect: tuple[int, int] = (9, 16),
    aspect_tolerance: float = 0.02,
    flicker_jump_threshold: float = 20.0,
    max_flicker_frequency: float = 2.0,
    loop_similarity_threshold: float = 0.95,
) -> VideoCheckReport:
    """Run full video qualification suite."""
    p = Path(video_path)
    if not p.exists():
        raise FileNotFoundError(f"Video file not found: {p}")

    aspect_res = check_aspect_ratio(p, target_ratio=target_aspect, tolerance=aspect_tolerance)
    flicker_res = check_flicker(
        p,
        jump_threshold=flicker_jump_threshold,
        max_flicker_frequency=max_flicker_frequency,
    )

    loop_res = None
    if is_loop:
        loop_res = check_loop_similarity(p, similarity_threshold=loop_similarity_threshold)

    overall_ok = aspect_res.ok and flicker_res.ok and (loop_res.ok if loop_res is not None else True)

    return VideoCheckReport(
        ok=overall_ok,
        video_path=str(p),
        aspect=aspect_res,
        flicker=flicker_res,
        loop=loop_res,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ffmpeg-based video motion & quality checks")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--loop", action="store_true", help="Enable loop first/last frame check")
    parser.add_argument("--target-aspect", nargs=2, type=int, default=[9, 16], help="Target aspect ratio W H")
    parser.add_argument("--aspect-tolerance", type=float, default=0.02)
    parser.add_argument("--jump-threshold", type=float, default=20.0)
    parser.add_argument("--max-flicker-freq", type=float, default=2.0)
    parser.add_argument("--loop-threshold", type=float, default=0.95)
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    args = parser.parse_args()

    report = check_video(
        args.video_path,
        is_loop=args.loop,
        target_aspect=(args.target_aspect[0], args.target_aspect[1]),
        aspect_tolerance=args.aspect_tolerance,
        flicker_jump_threshold=args.jump_threshold,
        max_flicker_frequency=args.max_flicker_freq,
        loop_similarity_threshold=args.loop_threshold,
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.format_text())

    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
