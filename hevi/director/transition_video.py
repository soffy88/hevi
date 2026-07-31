"""过渡视频生成（对标 ViMax camera_image_generator.generate_transition_video）。

当 Camera Tree 中两个 camera 之间视角/构图差异大时，
简单的 xfade 淡入淡出不够——需要生成**语义连贯**的过渡视频：

  父 camera 末帧 → [过渡视频] → 子 camera 首帧

过渡视频的作用是在视觉上桥接两个空间，让观众感知不到"跳切"。

本模块提供：
  - TransitionSpec — 过渡视频规格描述
  - generate_transition_video() — 主入口
  - bridge_shots() — 便捷函数
  - TransitionStrategy — 策略枚举（video_gen / morph / xfade_fallback）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ── 策略枚举 ──────────────────────────────────────────────────────────


class TransitionStrategy(str, Enum):
    VIDEO_GEN = "video_gen"      # 用视频生成模型生成过渡（最佳质量，最贵）
    MORPH = "morph"              # 帧插值 morph（中等质量，便宜）
    XFADE_FALLBACK = "xfade"     # FFmpeg xfade（兜底，最便宜）


# ── 数据模型 ──────────────────────────────────────────────────────────


@dataclass
class TransitionSpec:
    """过渡视频规格。"""

    source_frame: Path          # 父 camera 末帧
    target_frame: Path          # 子 camera 首帧
    output_path: Path           # 输出路径
    duration_s: float = 2.0     # 过渡时长（秒）
    strategy: TransitionStrategy = TransitionStrategy.VIDEO_GEN
    prompt: str = ""            # 过渡描述（video_gen 模式用）
    missing_info: str = ""      # 子 camera 相对于父 camera 缺少的元素
    fps: int = 24

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_frame": str(self.source_frame),
            "target_frame": str(self.target_frame),
            "output_path": str(self.output_path),
            "duration_s": self.duration_s,
            "strategy": self.strategy.value,
            "prompt": self.prompt,
            "missing_info": self.missing_info,
            "fps": self.fps,
        }


@dataclass
class TransitionResult:
    """过渡视频生成结果。"""

    output_path: Path
    strategy_used: TransitionStrategy
    duration_s: float
    fallback_reason: str = ""  # 如果使用 fallback，原因

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": str(self.output_path),
            "strategy_used": self.strategy_used.value,
            "duration_s": self.duration_s,
            "fallback_reason": self.fallback_reason,
        }


# ── 视频生成协议 ──────────────────────────────────────────────────────

VideoGenFn = Callable[
    [str, list[Path], Path, dict[str, Any]],
    Coroutine[Any, Any, Path],
]
"""视频生成函数：(prompt, ref_images, output_path, kwargs) → output_path"""


# ── 策略实现 ──────────────────────────────────────────────────────────


async def _generate_via_video_model(
    spec: TransitionSpec,
    video_gen: VideoGenFn | None = None,
) -> TransitionResult:
    """策略 1：用视频生成模型生成过渡视频。"""
    if video_gen is None:
        raise RuntimeError("video_gen function not provided")

    prompt = spec.prompt or (
        f"Smooth cinematic transition from the first frame to the second frame. "
        f"Duration: {spec.duration_s}s. "
        + (f"Introduce: {spec.missing_info}" if spec.missing_info else "")
    )

    output = await video_gen(
        prompt,
        [spec.source_frame, spec.target_frame],
        spec.output_path,
        {"duration_s": spec.duration_s, "fps": spec.fps},
    )

    return TransitionResult(
        output_path=output,
        strategy_used=TransitionStrategy.VIDEO_GEN,
        duration_s=spec.duration_s,
    )


async def _generate_via_morph(spec: TransitionSpec) -> TransitionResult:
    """策略 2：帧插值 morph（需要 ffmpeg minterpolate 或 rife）。"""
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = int(spec.duration_s * spec.fps)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(spec.duration_s),
        "-i", str(spec.source_frame),
        "-loop", "1", "-t", str(spec.duration_s),
        "-i", str(spec.target_frame),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={spec.duration_s}:offset=0,"
        f"fps={spec.fps}[out]",
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(spec.output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"morph transition failed: {stderr.decode(errors='replace')[-500:]}")

    return TransitionResult(
        output_path=spec.output_path,
        strategy_used=TransitionStrategy.MORPH,
        duration_s=spec.duration_s,
    )


async def _generate_via_xfade(spec: TransitionSpec) -> TransitionResult:
    """策略 3：FFmpeg xfade 兜底（最便宜）。"""
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(spec.duration_s),
        "-i", str(spec.source_frame),
        "-loop", "1", "-t", str(spec.duration_s),
        "-i", str(spec.target_frame),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={spec.duration_s}:offset=0[out]",
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(spec.output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"xfade failed: {stderr.decode(errors='replace')[-500:]}")

    return TransitionResult(
        output_path=spec.output_path,
        strategy_used=TransitionStrategy.XFADE_FALLBACK,
        duration_s=spec.duration_s,
    )


# ── 主入口 ────────────────────────────────────────────────────────────


async def generate_transition_video(
    spec: TransitionSpec,
    video_gen: VideoGenFn | None = None,
    *,
    fallback_chain: bool = True,
) -> TransitionResult:
    """生成过渡视频（带策略降级链）。

    Args:
        spec: 过渡规格
        video_gen: 视频生成函数（可选，用于 VIDEO_GEN 策略）
        fallback_chain: 是否启用降级链（video_gen → morph → xfade）

    Returns:
        TransitionResult
    """
    errors: list[str] = []

    # 策略 1: video_gen
    if spec.strategy == TransitionStrategy.VIDEO_GEN:
        if video_gen is not None:
            try:
                return await _generate_via_video_model(spec, video_gen)
            except Exception as e:
                errors.append(f"video_gen: {e}")
                logger.warning("video_gen transition failed: %s", e)
                if not fallback_chain:
                    raise
        else:
            errors.append("video_gen: no function provided")

    # 策略 2: morph
    if spec.strategy in (TransitionStrategy.VIDEO_GEN, TransitionStrategy.MORPH):
        try:
            return await _generate_via_morph(spec)
        except Exception as e:
            errors.append(f"morph: {e}")
            logger.warning("morph transition failed: %s", e)
            if not fallback_chain:
                raise

    # 策略 3: xfade (兜底)
    try:
        result = await _generate_via_xfade(spec)
        result.fallback_reason = "; ".join(errors) if errors else ""
        return result
    except Exception as e:
        errors.append(f"xfade: {e}")
        raise RuntimeError(
            f"all transition strategies failed: {'; '.join(errors)}"
        )


async def bridge_shots(
    *,
    source_frame: Path,
    target_frame: Path,
    output_dir: Path,
    transition_id: str = "bridge",
    duration_s: float = 2.0,
    prompt: str = "",
    missing_info: str = "",
    video_gen: VideoGenFn | None = None,
    strategy: TransitionStrategy = TransitionStrategy.VIDEO_GEN,
    fps: int = 24,
) -> TransitionResult:
    """便捷函数：生成两个 shot 之间的过渡视频。"""
    output_path = output_dir / f"transition_{transition_id}.mp4"

    spec = TransitionSpec(
        source_frame=source_frame,
        target_frame=target_frame,
        output_path=output_path,
        duration_s=duration_s,
        strategy=strategy,
        prompt=prompt,
        missing_info=missing_info,
        fps=fps,
    )

    return await generate_transition_video(spec, video_gen)


async def generate_all_transitions(
    transitions: list[TransitionSpec],
    video_gen: VideoGenFn | None = None,
    *,
    parallel: bool = True,
) -> list[TransitionResult]:
    """批量生成所有过渡视频。"""
    if parallel:
        tasks = [
            generate_transition_video(spec, video_gen)
            for spec in transitions
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        final: list[TransitionResult] = []
        for i, r in enumerate(results):
            if isinstance(r, TransitionResult):
                final.append(r)
            elif isinstance(r, Exception):
                logger.error("transition %d failed: %s", i, r)
        return final
    else:
        final = []
        for spec in transitions:
            try:
                result = await generate_transition_video(spec, video_gen)
                final.append(result)
            except Exception as e:
                logger.error("transition failed: %s", e)
        return final


def build_transition_prompt(
    *,
    source_description: str,
    target_description: str,
    missing_info: str = "",
    duration_s: float = 2.0,
) -> str:
    """构建过渡视频的生成提示词。"""
    parts = [
        f"Smooth cinematic camera transition, {duration_s}s duration.",
        f"From: {source_description}.",
        f"To: {target_description}.",
    ]
    if missing_info:
        parts.append(f"The transition should naturally introduce: {missing_info}.")
    parts.append("Maintain visual continuity and consistent lighting throughout.")
    return " ".join(parts)
