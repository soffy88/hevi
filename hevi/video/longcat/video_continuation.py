"""视频续接生成 (Video Continuation) — LongCat-Video generate_vc 机制适配。

LongCat-Video 的核心长视频能力:以上一段视频的末 N 帧为条件,续接生成下一段,
避免色彩漂移和质量退化。Hevi 已有 `continuity_reference_path` + VACE i2v 基础
设施(单末帧 reference_image),本模块补充:

  1. 显式续接策略枚举(no / single_frame / multi_frame)
  2. 镜头链式自动标注(apply_continuation_to_shots)
  3. 多末帧提取 + 帧间过渡条件(multi_frame 策略)
  4. 续接强度参数(cond_weight / cond_frames_count)

Hevi 侧对接:wan_local 走 VACE reference_image,云端走 keyframe_generate。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ContinuationMode",
    "ContinuationConfig",
    "ShotContinuation",
    "build_continuation_config",
    "apply_continuation_to_shots",
    "extract_video_last_frames",
    "compute_cond_frames_count",
]


class ContinuationMode(StrEnum):
    """续接策略。

    no           — 不续接(独立镜头,反打/切场)
    single_frame — 单末帧参考(已有 VACE i2v 路径,LongCat 基础模式)
    multi_frame  — 多末帧过渡(LongCat generate_vc 完整模式:末 N 帧条件化)
    """

    NO = "no"
    SINGLE_FRAME = "single_frame"
    MULTI_FRAME = "multi_frame"


@dataclass(frozen=True)
class ContinuationConfig:
    """单次续接的完整参数。"""

    mode: ContinuationMode
    prev_clip_path: Path | None = None
    last_frame_path: Path | None = None
    cond_frames_paths: list[Path] = field(default_factory=list)
    cond_frames_count: int = 1
    cond_weight: float = 1.0

    @property
    def has_condition(self) -> bool:
        return self.mode != ContinuationMode.NO and self.prev_clip_path is not None


@dataclass(frozen=True)
class ShotContinuation:
    """镜头级续接标注:shot_index + 对应 ContinuationConfig。"""

    shot_index: int
    config: ContinuationConfig
    is_first_shot: bool = False


def compute_cond_frames_count(
    duration_s: float,
    fps: int = 16,
    max_frames: int = 13,
    min_frames: int = 1,
) -> int:
    """根据时长计算条件帧数(LongCat 默认 13 帧 @ 15fps)。

    短镜头(≤3s):1 帧;中等(3-5s):5 帧;长(>5s):max_frames。
    """
    total_frames = int(duration_s * fps)
    if total_frames <= 3 * fps:
        return min_frames
    if total_frames <= 5 * fps:
        return 5
    return min(max_frames, total_frames // 3)


async def extract_video_last_frames(
    clip_path: Path,
    output_dir: Path,
    num_frames: int = 1,
    offset_s: float = 0.3,
) -> list[Path]:
    """从视频末尾提取 N 帧。

    Args:
        clip_path: 输入视频路径
        output_dir: 输出目录(帧图保存于此)
        num_frames: 提取帧数(1=single_frame, >1=multi_frame)
        offset_s: 末尾偏移秒(避免抓取到尾部黑帧)

    Returns:
        帧图路径列表,按时间顺序排列。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    if num_frames <= 1:
        # 单帧:ffmpeg -sseof 精确末帧
        out_path = output_dir / f"{clip_path.stem}_last.png"
        cmd = [
            "ffmpeg", "-y", "-sseof", f"-{offset_s}",
            "-i", str(clip_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if out_path.exists():
            paths.append(out_path)
        return paths

    # 多帧:先抽末段 N+2 帧,取最后 N 帧
    with tempfile.TemporaryDirectory(prefix="lc_frames_") as tmp:
        tmp_dir = Path(tmp)
        cmd = [
            "ffmpeg", "-y", "-sseof", f"-{max(1.0, offset_s * num_frames)}",
            "-i", str(clip_path),
            "-vf", f"select='eq(n\\,{num_frames - 1})'",  # 不工作,改用抽全部
            str(tmp_dir / "f_%04d.png"),
        ]
        # ffmpeg select filter 复杂,改用直接抽末段全帧再取末尾
        cmd = [
            "ffmpeg", "-y", "-sseof", f"-{max(2.0, num_frames / 10.0)}",
            "-i", str(clip_path),
            "-q:v", "2",
            str(tmp_dir / "f_%04d.png"),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        all_frames = sorted(tmp_dir.glob("*.png"))
        # 取最后 num_frames 帧
        selected = all_frames[-num_frames:] if len(all_frames) >= num_frames else all_frames
        for i, frame in enumerate(selected):
            dest = output_dir / f"{clip_path.stem}_cond_{i:03d}.png"
            import shutil
            shutil.copy2(frame, dest)
            paths.append(dest)

    return paths


def build_continuation_config(
    prev_clip_path: Path | None,
    last_frame_path: Path | None = None,
    cond_frames_paths: list[Path] | None = None,
    mode: ContinuationMode | None = None,
    cond_frames_count: int = 1,
    cond_weight: float = 1.0,
) -> ContinuationConfig:
    """构造续接配置。

    如果 mode=None,根据可用信息自动推断:
    - prev_clip_path=None → NO
    - 仅 last_frame → SINGLE_FRAME
    - 有 cond_frames_paths → MULTI_FRAME
    """
    if prev_clip_path is None:
        return ContinuationConfig(mode=ContinuationMode.NO)

    if mode is None:
        if cond_frames_paths and len(cond_frames_paths) > 1:
            mode = ContinuationMode.MULTI_FRAME
        else:
            mode = ContinuationMode.SINGLE_FRAME

    return ContinuationConfig(
        mode=mode,
        prev_clip_path=prev_clip_path,
        last_frame_path=last_frame_path,
        cond_frames_paths=cond_frames_paths or [],
        cond_frames_count=cond_frames_count,
        cond_weight=cond_weight,
    )


def apply_continuation_to_shots(
    clip_paths: list[Path],
    last_frame_paths: list[Path | None],
    *,
    mode: ContinuationMode = ContinuationMode.SINGLE_FRAME,
    cond_frames_count: int = 1,
    cond_weight: float = 1.0,
    continues_mask: list[bool] | None = None,
) -> list[ShotContinuation]:
    """为镜头列表标注续接信息。

    Args:
        clip_paths: 各镜头的视频路径(已生成)
        last_frame_paths: 各镜头的末帧路径(已提取)
        mode: 续接策略
        cond_frames_count: multi_frame 模式下的条件帧数
        cond_weight: 条件权重(0.0-1.0)
        continues_mask: 每个镜头是否续接上一镜头(True=续接,False=独立)
                       None 时默认:第一个不续接,其余全部续接

    Returns:
        ShotContinuation 列表,与 clip_paths 一一对应。
    """
    n = len(clip_paths)
    if len(last_frame_paths) != n:
        raise ValueError(
            f"clip_paths ({n}) 和 last_frame_paths ({len(last_frame_paths)}) 长度不匹配"
        )
    if continues_mask is None:
        continues_mask = [False] + [True] * (n - 1)
    elif len(continues_mask) != n:
        raise ValueError(
            f"clip_paths ({n}) 和 continues_mask ({len(continues_mask)}) 长度不匹配"
        )

    results: list[ShotContinuation] = []
    for i in range(n):
        if i == 0 or not continues_mask[i]:
            results.append(ShotContinuation(
                shot_index=i,
                config=ContinuationConfig(mode=ContinuationMode.NO),
                is_first_shot=(i == 0),
            ))
            continue

        prev_clip = clip_paths[i - 1]
        prev_frame = last_frame_paths[i - 1]

        # multi_frame 模式需要前序多帧,此处用 prev_frame 做 best-effort
        cond_paths: list[Path] = []
        if mode == ContinuationMode.MULTI_FRAME and prev_frame is not None:
            cond_paths = [prev_frame] * cond_frames_count  # 占位,实际应抽多帧

        cfg = build_continuation_config(
            prev_clip_path=prev_clip,
            last_frame_path=prev_frame,
            cond_frames_paths=cond_paths if cond_paths else None,
            mode=mode,
            cond_frames_count=cond_frames_count,
            cond_weight=cond_weight,
        )
        results.append(ShotContinuation(shot_index=i, config=cfg))

    return results
