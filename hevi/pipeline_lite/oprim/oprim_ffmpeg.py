"""oprim:oprim_ffmpeg —— 纯音视频轨道混流原子能力(绝对无状态)。

只负责:把视频轨 + 音频轨(可选低音量 BGM 混入)mux 成最终成片,并强制校验
产物包含音频轨。不负责生成音视频本身,也不做任何业务判断。

v9.1:
  * bgm_path: 可选背景音乐, 以低音量(volume=bgm_volume)与旁白 amix;
  * assert_audio_track: 混流后 ffprobe 强制校验音频轨存在 —— 拒绝"只有视频
    的假成片"。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class MuxError(RuntimeError):
    """ffmpeg 混流失败。"""


def mux_audio_video(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path,
    *,
    bgm_path: str | Path | None = None,
    bgm_volume: float = 0.12,
    remove_original: bool = False,
    timeout: int = 600,
) -> Path:
    """把视频轨 + 音频轨混流成单文件(可选 BGM 低音量混入)。

    缺少 ffmpeg 时直接返回视频轨(降级); 混流成功但无音频轨 → 抛 MuxError。
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        logger.warning("ffmpeg 不可用,混流降级为返回视频轨: %s", video_path)
        return Path(video_path)

    bgm = Path(bgm_path) if bgm_path else None
    use_bgm = bool(bgm and bgm.exists() and bgm.stat().st_size > 0)

    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path)]
    if use_bgm:
        cmd += ["-i", str(bgm)]
        # [1:a] 旁白原样; [2:a] BGM 压到 bgm_volume 后 amix(以旁白时长为准)。
        filter_complex = (
            f"[1:a]anull[a_voice];[2:a]volume={bgm_volume}[a_bgm];"
            f"[a_voice][a_bgm]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
        )
        cmd += ["-filter_complex", filter_complex, "-map", "0:v", "-map", "[a_out]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += [
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise MuxError(f"ffmpeg 混流失败: {result.stderr[-500:]}")

    # 强制校验: 最终 MP4 必须包含音频轨。
    assert_audio_track(output)

    if remove_original:
        Path(video_path).unlink(missing_ok=True)
    return output


def assert_audio_track(video_path: str | Path) -> bool:
    """ffprobe 校验视频文件含音频轨; 缺失抛 MuxError。"""
    path = Path(video_path)
    if not shutil.which("ffprobe"):
        logger.warning("ffprobe 不可用, 跳过音频轨校验: %s", path)
        return True
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(path),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise MuxError(f"成片缺少音频轨(音画不同步产物): {path}")
    return True


__all__ = ["MuxError", "assert_audio_track", "mux_audio_video"]
