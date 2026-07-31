"""场景检测 —— PySceneDetect / ffmpeg 场景切换检测。

将视频按场景切割,输出每个场景的起止时间、关键帧、持续时长。
供参考视频分析、分段剪辑等下游消费。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    index: int
    start_s: float
    end_s: float
    duration_s: float
    keyframe_path: Path | None = None


def detect_scenes(
    video_path: Path,
    output_dir: Path,
    *,
    threshold: float = 27.0,
    extract_keyframes: bool = True,
) -> list[Scene]:
    """检测视频中的场景切换。

    Args:
        video_path: 视频文件路径
        output_dir: 输出目录(关键帧图片)
        threshold: 场景切换阈值(越低越敏感,默认 27.0)
        extract_keyframes: 是否提取每个场景的首帧

    Returns:
        Scene 列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 优先用 PySceneDetect,回退到 ffmpeg scene filter
    try:
        return _detect_pyscenedetect(video_path, output_dir, threshold=threshold,
                                       extract_keyframes=extract_keyframes)
    except ImportError:
        return _detect_ffmpeg(video_path, output_dir, threshold=threshold,
                              extract_keyframes=extract_keyframes)


def _detect_pyscenedetect(
    video_path: Path, output_dir: Path, *, threshold: float, extract_keyframes: bool
) -> list[Scene]:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)

    scene_list = scene_manager.get_scene_list()
    scenes = []
    for i, (start, end) in enumerate(scene_list):
        scene = Scene(
            index=i,
            start_s=start.get_seconds(),
            end_s=end.get_seconds(),
            duration_s=(end - start).get_seconds(),
        )
        if extract_keyframes:
            kf_path = output_dir / f"scene_{i:03d}.jpg"
            _extract_frame_at(video_path, scene.start_s + 0.1, kf_path)
            scene.keyframe_path = kf_path
        scenes.append(scene)

    return scenes


def _detect_ffmpeg(
    video_path: Path, output_dir: Path, *, threshold: float, extract_keyframes: bool
) -> list[Scene]:
    """用 ffmpeg scene filter 检测场景切换。"""
    # ffmpeg 输出格式: "scene:0.987654 -> t:12.345"
    ffmpeg_threshold = threshold / 100.0  # ffmpeg 用 0-1

    result = subprocess.run(
        [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"select='gt(scene,{ffmpeg_threshold})',showinfo",
            "-f", "null", "-"
        ],
        capture_output=True, text=True, timeout=300,
    )

    import re
    timestamps = []
    for line in result.stderr.split("\n"):
        m = re.search(r"pts_time:(\d+\.?\d*)", line)
        if m:
            timestamps.append(float(m.group(1)))

    # 获取总时长
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    total_duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0

    # 构造 Scene 列表
    boundaries = [0.0, *timestamps, total_duration]
    scenes = []
    for i in range(len(boundaries) - 1):
        scene = Scene(
            index=i,
            start_s=boundaries[i],
            end_s=boundaries[i + 1],
            duration_s=boundaries[i + 1] - boundaries[i],
        )
        if extract_keyframes:
            kf_path = output_dir / f"scene_{i:03d}.jpg"
            _extract_frame_at(video_path, scene.start_s + 0.1, kf_path)
            scene.keyframe_path = kf_path
        scenes.append(scene)

    return scenes


def _extract_frame_at(video_path: Path, timestamp: float, output: Path) -> None:
    """提取视频指定时间点的帧。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",
            str(output),
        ],
        timeout=30,
    )
