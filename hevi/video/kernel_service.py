from pathlib import Path
from typing import Any, Literal

from oprim import ltx2_cloud_generate, video_generate

from hevi.observability import track_provider_call
from hevi.video.provider_config import VideoProvider

VideoProviderLiteral = Literal["ltx2_cloud", "wan_cloud"]


async def generate_clip(
    *,
    config: Any,
    provider: VideoProviderLiteral | VideoProvider,
    mode: Literal["t2v", "i2v"],
    prompt: str,
    reference_image: Path | None = None,
    duration_s: float,
    resolution: tuple[int, int] = (1280, 720),
    audio_enabled: bool = True,
    output_path: Path,
) -> Path:
    """Pluggable double-cloud video generation dispatch.

    Args:
        config: Provider configuration object.
        provider: Choice of video provider (ltx2_cloud or wan_cloud).
        mode: Generation mode ('t2v' for text-to-video, 'i2v' for image-to-video).
        prompt: Text prompt for generation.
        reference_image: Optional path to reference image for i2v mode.
        duration_s: Target duration in seconds.
        resolution: Target resolution (width, height).
        audio_enabled: Whether to enable audio generation if supported.
        output_path: Path where the generated video will be saved.

    Returns:
        Path: The path to the generated video file.

    Raises:
        ValueError: If an unknown provider or mode is specified.
    """
    if mode not in ("t2v", "i2v"):
        raise ValueError(f"Invalid mode: {mode}. Must be 't2v' or 'i2v'.")

    # Normalize provider string
    provider_str = str(provider)

    async with track_provider_call(provider_str):
        if provider_str == VideoProvider.LTX2_CLOUD:
            # Mypy might think ltx2_cloud_generate is a module; it's a function.
            return await ltx2_cloud_generate(  # type: ignore[operator, no-any-return]
                config=config,
                mode=mode,
                prompt=prompt,
                reference_image=reference_image,
                duration_s=duration_s,
                resolution=resolution,
                audio_enabled=audio_enabled,
                output_path=output_path,
            )
        elif provider_str == VideoProvider.WAN_CLOUD:
            # wan_cloud in oprim.video_generate might not support resolution/audio_enabled
            # directly in M2 signature following the provided snippet exactly.
            return await video_generate(  # type: ignore[operator, no-any-return]
                config=config,
                provider="wan_cloud",
                mode=mode,
                prompt=prompt,
                reference_image=reference_image,
                duration_s=duration_s,
                output_path=output_path,
            )
        else:
            raise ValueError(f"Unknown video provider: {provider_str}")
