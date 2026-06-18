from pathlib import Path
from typing import Any, Literal

from oprim import ltx2_cloud_generate, video_generate

from hevi.cost.pricing_table import LTX2_ENDPOINTS
from hevi.observability import track_provider_call
from hevi.video.provider_config import VideoProvider
from hevi.video.quality_profile import DEFAULT_QUALITY, get_quality_profile
from hevi.video.wan_local_service import wan_local_generate

VideoProviderLiteral = Literal["ltx2_cloud", "wan_cloud", "wan_local"]


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
    quality: str = DEFAULT_QUALITY,
    ltx2_tier: Literal["fast", "pro"] = "fast",
) -> Path:
    """Pluggable double-cloud video generation dispatch with quality params.

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
        quality: Quality tier name ('standard', 'high', 'ultra'). Defaults to 'standard'.
        ltx2_tier: fal.ai LTX-2 billing tier ('fast' or 'pro'). Passed via FAL_BASE_URL
            config override. M1 ltx2_cloud_generate has no native tier param — endpoint
            is selected by setting "FAL_BASE_URL" in the config dict.

    Returns:
        Path: The path to the generated video file.

    Raises:
        ValueError: If an unknown provider, mode, or quality is specified.
    """
    if mode not in ("t2v", "i2v"):
        raise ValueError(f"Invalid mode: {mode}. Must be 't2v' or 'i2v'.")

    profile = get_quality_profile(quality)
    provider_str = str(provider)

    async with track_provider_call(provider_str):
        if provider_str == VideoProvider.LTX2_CLOUD:
            # Merge tier endpoint into config; M1 reads FAL_BASE_URL from the config dict
            ltx2_config: dict[str, Any] = dict(config) if isinstance(config, dict) else {}
            ltx2_config["FAL_BASE_URL"] = LTX2_ENDPOINTS[ltx2_tier]
            return await ltx2_cloud_generate(  # type: ignore[no-any-return]
                config=ltx2_config,
                mode=mode,
                prompt=prompt,
                reference_image=reference_image,
                duration_s=duration_s,
                resolution=resolution,
                audio_enabled=audio_enabled,
                output_path=output_path,
                fps=profile.fps,
                bitrate_kbps=profile.bitrate_kbps,
            )
        elif provider_str == VideoProvider.WAN_CLOUD:
            return await video_generate(  # type: ignore[no-any-return]
                config=config,
                provider="wan_cloud",
                mode=mode,
                prompt=prompt,
                reference_image=reference_image,
                duration_s=duration_s,
                output_path=output_path,
                fps=profile.fps,
                bitrate_kbps=profile.bitrate_kbps,
            )
        elif provider_str == VideoProvider.WAN_LOCAL:
            return await wan_local_generate(
                prompt=prompt,
                output_path=output_path,
            )
        else:
            raise ValueError(f"Unknown video provider: {provider_str}")
