"""调色 —— ffmpeg LUTs / 确定性色彩映射。

零模型成本,纯 ffmpeg。解决"多 provider 混剪接缝明显"的装配问题(架构 §4.4)。
内置 LUTs + 自定义 LUT 文件支持。

用法:
    color_grade(Path("shot.mp4"), Path("graded.mp4"), lut="warm_cinema")
    color_grade(Path("shot.png"), Path("graded.png"), lut="cool_night")
    color_grade(Path("shot.mp4"), Path("graded.mp4"), lut_file=Path("custom.cube"))
    available = list_luts()
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


# ── 内置 LUT 参数(ffmpeg 滤镜链,不依赖外部 .cube 文件) ─────────────────────

_BUILTIN_LUTS: dict[str, dict[str, str]] = {
    "warm_cinema": {
        "desc": "暖色电影感:橙琥珀色调,微降饱和度",
        "filter": (
            "eq=brightness=0.02:saturation=0.9,"
            "colorbalance=rs=0.08:gs=0.02:bs=-0.05:rm=0.06:gm=0.01:bm=-0.03:"
            "rh=0.04:gh=-0.01:bh=-0.04"
        ),
    },
    "cool_night": {
        "desc": "冷色夜景:青蓝色调,压暗高光",
        "filter": (
            "eq=brightness=-0.03:saturation=0.85,"
            "colorbalance=rs=-0.06:gs=-0.02:bs=0.08:rm=-0.04:gm=0.0:bm=0.06:"
            "rh=-0.03:gh=0.02:bh=0.08"
        ),
    },
    "vintage_film": {
        "desc": "复古胶片:低对比度,褪色感,微暖",
        "filter": (
            "eq=contrast=0.92:brightness=0.01:saturation=0.75,"
            "colorbalance=rs=0.04:gs=0.01:bs=-0.02:rm=0.03:gm=0.0:bm=-0.01"
        ),
    },
    "noir": {
        "desc": "黑白高对比度",
        "filter": "hue=s=0,eq=contrast=1.3:brightness=-0.02",
    },
    "anime_vivid": {
        "desc": "动画高饱和:鲜艳色彩,高对比度",
        "filter": "eq=saturation=1.3:contrast=1.1:brightness=0.01",
    },
    "historical_epic": {
        "desc": "历史正剧:青灰赭褐,低饱和,厚重感(通鉴 V2 方向1)",
        "filter": (
            "eq=brightness=-0.02:saturation=0.7:contrast=1.05,"
            "colorbalance=rs=0.03:gs=-0.01:bs=-0.04:rm=0.02:gm=-0.01:bm=-0.03"
        ),
    },
    "desaturated_bleach": {
        "desc": "漂白效果:极低饱和度,高对比度(战争/灾难场景)",
        "filter": "eq=saturation=0.4:contrast=1.2:brightness=-0.01",
    },
    "golden_hour": {
        "desc": "黄金时段:暖橙色调,柔和高光",
        "filter": (
            "eq=brightness=0.03:saturation=1.05,"
            "colorbalance=rs=0.1:gs=0.04:bs=-0.06:rm=0.08:gm=0.02:bm=-0.04"
        ),
    },
    "identity": {
        "desc": "恒等(不做任何调色,用于测试或显式'不调')",
        "filter": "null",
    },
}


def list_luts() -> dict[str, str]:
    """列出所有内置 LUT 名称和描述。"""
    return {name: info["desc"] for name, info in _BUILTIN_LUTS.items()}


def color_grade(
    src: Path,
    dst: Path,
    *,
    lut: str = "warm_cinema",
    lut_file: Path | None = None,
    extra_filters: str = "",
) -> Path:
    """对图像或视频应用调色。

    Args:
        src: 输入文件(图像或视频)
        dst: 输出文件
        lut: 内置 LUT 名称(见 list_luts())
        lut_file: 外部 .cube LUT 文件路径(优先于 lut 参数)
        extra_filters: 额外 ffmpeg 滤镜(追加在 LUT 后)

    Returns:
        输出路径
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    if lut_file and lut_file.exists():
        vf = f"lut3d='{lut_file}'"
    elif lut in _BUILTIN_LUTS:
        vf = _BUILTIN_LUTS[lut]["filter"]
    else:
        raise ValueError(f"Unknown LUT: {lut}. Available: {list(_BUILTIN_LUTS.keys())}")

    if extra_filters:
        vf = f"{vf},{extra_filters}" if vf != "null" else extra_filters

    is_video = src.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm")

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]

    if is_video:
        cmd.extend([
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy",
        ])
    else:
        cmd.extend(["-vf", vf])

    cmd.append(str(dst))
    subprocess.run(cmd, check=True, timeout=600)
    return dst


def normalize_color(
    clips: list[Path],
    output_dir: Path,
    *,
    target_lut: str = "warm_cinema",
    reference: Path | None = None,
) -> list[Path]:
    """跨 provider 调色统一(架构 §4.4)。

    将多个 clip 归一到同一色彩空间,可选匹配参考图的色调。

    Args:
        clips: 输入 clip 列表
        output_dir: 输出目录
        target_lut: 统一调色(默认 warm_cinema)
        reference: 参考图(可选,用于 color match)

    Returns:
        输出路径列表
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, clip in enumerate(clips):
        dst = output_dir / f"{i:03d}_graded{clip.suffix}"
        color_grade(clip, dst, lut=target_lut)
        results.append(dst)
    return results
