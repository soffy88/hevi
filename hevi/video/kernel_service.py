from pathlib import Path
from typing import Any, Literal

from oprim import ltx2_cloud_generate, video_generate

from hevi.cost.pricing_table import LTX2_ENDPOINTS
from hevi.observability import track_provider_call
from hevi.video.provider_config import VideoProvider
from hevi.video.quality_profile import DEFAULT_QUALITY, get_quality_profile
from hevi.video.wan_local_service import wan_local_generate

VideoProviderLiteral = Literal["ltx2_cloud", "wan_cloud", "wan_local"]

# wan2.1-1.3B 原生约 16fps,显存上限决定分辨率约 480p 级。下列函数把上层
# quality_profile 的目标(可能是竖屏 720×1280@24/30)夹取到 wan 可行规格,
# 并保留朝向;最终成片由装配器重编码到真实目标分辨率/帧率。
_WAN_LOCAL_FPS = 16
_WAN_MAX_FRAMES = 161  # ~10s @16fps,1.3B 单卡 10GB 的务实上限


def _wan_local_size(resolution: tuple[int, int]) -> tuple[int, int]:
    """把目标分辨率夹取为 wan 可行的 480p 级,保留朝向(竖/横/方)。"""
    w, h = resolution
    if w < h:        # 竖屏
        return (480, 832)
    if w > h:        # 横屏
        return (832, 480)
    return (576, 576)  # 方形


def _wan_local_frames(duration_s: float, _target_fps: int) -> int:
    """由目标时长换算 wan 帧数(按 16fps 原生),夹取到 [16, _WAN_MAX_FRAMES]。"""
    frames = round(max(1.0, duration_s) * _WAN_LOCAL_FPS)
    return max(16, min(frames, _WAN_MAX_FRAMES))


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

    # RFC-002 item 9: 单片内核入口校验 provider 能力,非法分辨率/时长/fps/模式
    # 在消耗算力/API 前 fail-fast(此前 validate_request 是死代码)。
    from hevi.video.capability_guard import PROVIDER_LIMITS, validate_request
    if provider_str in PROVIDER_LIMITS:
        await validate_request(
            provider=provider_str, mode=mode, resolution=resolution,
            duration_s=duration_s, fps=profile.fps,
        )

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
        if provider_str == VideoProvider.WAN_CLOUD:
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
        if provider_str in (VideoProvider.WAN_LOCAL, VideoProvider.LTX2_LOCAL):
            # ltx2_local 路由到 wan_local: 本机无独立 LTX2 local 推理实现。
            # RFC-002 item 1/3: 贯通分辨率/帧数 + i2v 参考图(wan2.1-1.3B 上限 ~480p,
            # 按目标朝向夹取; reference_image 非空 → VACE 参考条件化)。
            w, h = _wan_local_size(resolution)
            frames = _wan_local_frames(duration_s, profile.fps)
            return await wan_local_generate(
                prompt=prompt,
                output_path=output_path,
                size=(w, h),
                frame_num=frames,
                negative_prompt=None,
                reference_image=reference_image if mode == "i2v" else None,
            )
        raise ValueError(f"Unknown video provider: {provider_str}")
