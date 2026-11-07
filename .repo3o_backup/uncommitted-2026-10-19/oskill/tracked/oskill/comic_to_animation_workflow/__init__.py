"""oskill.comic_to_animation_workflow — 漫画图 → 角色动作流畅动画.

Combines LLM analysis + oprim.image_generate + oprim.image_to_video +
oprim.video_concat to produce a smooth animation from a comic panel.

Example:
    >>> from pathlib import Path
    >>> from oskill.comic_to_animation_workflow import comic_to_animation_workflow
    >>> out = await comic_to_animation_workflow(
    ...     comic_image=Path("panel.png"), llm=my_llm,
    ...     image_provider="flux", video_provider="wan22_local",
    ...     output_path=Path("animation.mp4"),
    ... )

Raises:
    FileNotFoundError: comic_image 不存在
    ComicToAnimationError: 任一步骤失败
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oskill._llm_caller import LLMCaller


class ComicToAnimationError(Exception):
    """Comic-to-animation workflow failed."""


_ANALYSIS_PROMPT = (
    "You are an animation director. Analyze this comic panel and extract 3 key action frames. "
    "For each frame provide a detailed image prompt and a short motion description. "
    "Return STRICT JSON array of exactly 3 objects:\n"
    '[{"description": "<image prompt>", "motion": "<motion desc>"}, ...]\n'
    "No markdown."
)


async def comic_to_animation_workflow(
    *,
    comic_image: Path,
    llm: LLMCaller,
    image_provider: str,
    video_provider: str,
    output_path: Path,
) -> Path:
    """Convert a comic panel into a smooth character animation.

    Internal oprim composition:
    - oprim.image_generate (one keyframe per action step, ≥2 calls)
    - oprim.image_to_video (one video clip per keyframe)
    - oprim.video_concat (merge clips into final animation)
    - LLM call for comic analysis / frame extraction (inlined; not an independent oprim)

    Args:
        comic_image: Source comic panel image path.
        llm: LLMCaller to analyze the comic and extract key frames.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        video_provider: Provider name (category='image_to_video') for oprim.image_to_video.
        output_path: Destination path for the final animation video.

    Returns:
        output_path after writing the final animation.

    Raises:
        FileNotFoundError: comic_image does not exist.
        ComicToAnimationError: LLM analysis failed, image_gen failed,
            image_to_video failed, video_concat failed, or output not produced.

    Example:
        >>> out = await comic_to_animation_workflow(
        ...     comic_image=Path("panel.png"), llm=my_llm,
        ...     image_provider="flux", video_provider="wan22_local",
        ...     output_path=Path("animation.mp4"),
        ... )
    """
    if not comic_image.exists():
        raise FileNotFoundError(f"comic_image not found: {comic_image}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_path.parent / f"_ctmp_{output_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: LLM analyzes comic → extracts key frames
    try:
        resp: dict[str, Any] = llm(messages=[{"role": "user", "content": _ANALYSIS_PROMPT}])
        frames_data: list[Any] = json.loads(resp.get("content", "[]"))
    except Exception as exc:
        raise ComicToAnimationError(f"LLM comic analysis failed: {exc}") from exc

    if not frames_data:
        raise ComicToAnimationError("LLM returned no frames")

    # Step 2: Generate keyframe images (lazy import)
    from oprim.image_generate import ImageGenError, image_generate

    keyframes: list[Path] = []
    for i, frame in enumerate(frames_data):
        img_path = tmp_dir / f"keyframe_{i:02d}.png"
        desc = str(frame.get("description", f"comic frame {i}"))
        try:
            await image_generate(provider=image_provider, prompt=desc, output_path=img_path)
        except ImageGenError as exc:
            raise ComicToAnimationError(f"Keyframe {i} image_gen failed: {exc}") from exc
        except Exception as exc:
            raise ComicToAnimationError(f"Unexpected error for keyframe {i}: {exc}") from exc
        keyframes.append(img_path)

    # Step 3: Convert each keyframe to a video clip (lazy import)
    from oprim import ImageToVideoError, image_to_video

    clips: list[Path] = []
    for i, (kf, frame) in enumerate(zip(keyframes, frames_data)):
        clip_path = tmp_dir / f"clip_{i:02d}.mp4"
        motion = str(frame.get("motion", "smooth transition"))
        try:
            await image_to_video(
                provider=video_provider,
                reference_image=kf,
                motion_prompt=motion,
                duration_s=2.0,
                output_path=clip_path,
            )
        except ImageToVideoError as exc:
            raise ComicToAnimationError(f"Clip {i} image_to_video failed: {exc}") from exc
        except Exception as exc:
            raise ComicToAnimationError(f"Unexpected error for clip {i}: {exc}") from exc
        clips.append(clip_path)

    # Step 4: Concatenate clips (lazy import)
    from oprim.video_concat import VideoConcatError, video_concat

    try:
        await video_concat(inputs=clips, output_path=output_path)
    except VideoConcatError as exc:
        raise ComicToAnimationError(f"video_concat failed: {exc}") from exc
    except Exception as exc:
        raise ComicToAnimationError(f"Unexpected error during concat: {exc}") from exc

    if not output_path.exists():
        raise ComicToAnimationError(f"Output not produced: {output_path}")

    return output_path


__all__ = ["comic_to_animation_workflow", "ComicToAnimationError"]
