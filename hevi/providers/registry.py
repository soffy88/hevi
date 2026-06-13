"""L2 provider registry — 复用 obase.ProviderRegistry (L-021, L-022).

All methods are classmethods; use ProviderRegistry.register() directly.
"""

from obase.provider_registry import ProviderRegistry
from oprim import avatar_generate, ltx2_cloud_generate, vibevoice_synthesize, video_generate

__all__ = ["ProviderRegistry", "register_all_providers"]


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # Video Providers
    ProviderRegistry.register(
        "video", "ltx2_cloud", ltx2_cloud_generate  # type: ignore[arg-type]
    )
    ProviderRegistry.register(
        "video",
        "wan_cloud",
        lambda **kwargs: video_generate(  # type: ignore[operator]
            provider="wan_cloud", **kwargs
        ),
    )

    # Audio Providers
    ProviderRegistry.register(
        "audio", "vibevoice", vibevoice_synthesize  # type: ignore[arg-type]
    )
    ProviderRegistry.register(
        "audio",
        "duix",
        lambda **kwargs: avatar_generate(  # type: ignore[operator]
            provider="duix", **kwargs
        ),
    )
