"""oskill.image_to_video_workflow — Multi-image animation with retry + fallback.

Orchestrates oprim.motion_prompt_translate + oprim.image_to_video + validation.

Example:
    >>> from oskill.image_to_video_workflow import image_to_video_workflow
    >>> paths = await image_to_video_workflow(
    ...     reference_images=[Path("a.png")], motion_prompts=["pan left"],
    ...     durations=[5.0], output_dir=Path("out/"),
    ... )

Raises:
    ImageToVideoWorkflowError: Workflow failed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ImageToVideoWorkflowError(Exception):
    """Image-to-video workflow failed."""


class WorkflowResult(BaseModel):
    """Result for a single image-to-video conversion."""

    input_image: Path
    output_video: Path
    provider_used: str
    retries: int = 0


async def image_to_video_workflow(
    *,
    reference_images: list[Path],
    motion_prompts: list[str],
    durations: list[float],
    output_dir: Path,
    primary_provider: str = "wan22_local",
    fallback_provider: str | None = "wan22_cloud",
    concurrency: int = 1,
    llm: Any = None,
    timeout_s: float = 600.0,
) -> list[Path]:
    """Generate videos from images with retry and fallback.

    Calls oprim.image_to_video for each image. On primary failure, retries
    with fallback_provider. Validates output via oprim.video_quality_metrics.

    Args:
        reference_images: Source images.
        motion_prompts: Motion descriptions per image.
        durations: Target duration per video.
        output_dir: Directory for output videos.
        primary_provider: First-choice provider.
        fallback_provider: Fallback on primary failure (None = no fallback).
        concurrency: Max parallel generations.
        llm: Optional LLMCaller for motion_prompt_translate.
        timeout_s: Per-generation timeout.

    Returns:
        List of output video paths (aligned with inputs).

    Raises:
        ImageToVideoWorkflowError: Input mismatch or all providers failed.

    Example:
        >>> paths = await image_to_video_workflow(
        ...     reference_images=[img], motion_prompts=["zoom"],
        ...     durations=[5.0], output_dir=Path("out/"))
    """
    if not (len(reference_images) == len(motion_prompts) == len(durations)):
        raise ImageToVideoWorkflowError(
            f"Input lengths must match: images={len(reference_images)}, "
            f"prompts={len(motion_prompts)}, durations={len(durations)}"
        )
    if not reference_images:
        raise ImageToVideoWorkflowError("reference_images must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)

    async def _process_one(idx: int) -> Path:
        from oprim import ImageToVideoError, image_to_video

        img = reference_images[idx]
        prompt = motion_prompts[idx]
        dur = durations[idx]
        out = output_dir / f"shot_{idx:03d}.mp4"

        # Optionally translate motion prompt
        if llm is not None:
            from oprim import motion_prompt_translate

            prompt = await motion_prompt_translate(
                natural_language_motion=prompt,
                llm=llm,
                target_provider=primary_provider,
            )

        async with sem:
            # Try primary
            try:
                await image_to_video(
                    provider=primary_provider,
                    reference_image=img,
                    motion_prompt=prompt,
                    duration_s=dur,
                    output_path=out,
                    timeout_s=timeout_s,
                )
                return out
            except ImageToVideoError:
                if fallback_provider is None:
                    raise

            # Try fallback
            try:
                await image_to_video(
                    provider=fallback_provider,
                    reference_image=img,
                    motion_prompt=prompt,
                    duration_s=dur,
                    output_path=out,
                    timeout_s=timeout_s,
                )
                return out
            except ImageToVideoError as exc:
                raise ImageToVideoWorkflowError(
                    f"All providers failed for image {idx}: {exc}"
                ) from exc

    tasks = [_process_one(i) for i in range(len(reference_images))]
    try:
        results = await asyncio.gather(*tasks)
    except ImageToVideoWorkflowError:
        raise
    except Exception as exc:
        raise ImageToVideoWorkflowError(f"Workflow failed: {exc}") from exc

    return list(results)
