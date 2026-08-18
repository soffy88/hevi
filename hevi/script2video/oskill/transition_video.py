"""机位过渡视频:video_gen → xfade 降级。

组合: `build_transition_prompt` + 注入的 video_gen / ffmpeg xfade。
3O 归属(待上游): `oskill.transition_video`。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from hevi.script2video.oprim.transition_prompt import build_transition_prompt
from hevi.script2video.schemas import TransitionResult, TransitionSpec

logger = logging.getLogger(__name__)

VideoGenFn = Callable[..., Awaitable[Path]]


async def generate_transition_video(
    spec: TransitionSpec,
    *,
    video_gen: VideoGenFn | None = None,
    fallback_chain: bool = True,
) -> TransitionResult:
    prompt = spec.prompt or build_transition_prompt(
        spec.first_shot_visual_desc,
        spec.second_shot_visual_desc,
        missing_info=spec.missing_info,
        duration_s=spec.duration_s,
    )
    spec.prompt = prompt
    errors: list[str] = []

    if spec.strategy == "video_gen" or fallback_chain:
        if video_gen is None:
            errors.append("video_gen: no function provided")
        else:
            try:
                await video_gen(
                    prompt=prompt,
                    output_path=spec.output_path,
                    reference_image_paths=[str(spec.source_frame)],
                    duration_s=spec.duration_s,
                )
                return TransitionResult(
                    output_path=spec.output_path,
                    strategy_used="video_gen",
                    duration_s=spec.duration_s,
                )
            except Exception as exc:
                logger.warning("video_gen transition failed: %s", exc)
                errors.append(f"video_gen: {exc}")
                if not fallback_chain:
                    raise

    if fallback_chain or spec.strategy in {"morph", "xfade_fallback"}:
        try:
            await _generate_via_xfade(spec)
            return TransitionResult(
                output_path=spec.output_path,
                strategy_used="xfade_fallback",
                duration_s=spec.duration_s,
                fallback_reason="; ".join(errors) or None,
            )
        except Exception as exc:
            errors.append(f"xfade: {exc}")
            if not fallback_chain:
                raise

    raise RuntimeError("all transition strategies failed: " + "; ".join(errors))


async def generate_all_transitions(
    specs: list[TransitionSpec],
    *,
    video_gen: VideoGenFn | None = None,
) -> list[TransitionResult]:
    results: list[TransitionResult] = []
    for spec in specs:
        try:
            results.append(await generate_transition_video(spec, video_gen=video_gen))
        except Exception as exc:
            logger.error("transition failed: %s", exc)
    return results


async def _generate_via_xfade(spec: TransitionSpec) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found")
    spec.output_path.parent.mkdir(parents=True, exist_ok=True)
    end_frame = spec.target_frame or spec.source_frame
    duration = max(0.2, spec.duration_s)
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-t",
        str(duration),
        "-i",
        str(spec.source_frame),
        "-loop",
        "1",
        "-t",
        str(duration),
        "-i",
        str(end_frame),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={duration}:offset=0,format=yuv420p",
        "-t",
        str(duration),
        "-r",
        str(spec.fps),
        str(spec.output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-400:])
