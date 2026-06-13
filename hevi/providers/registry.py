"""L2 provider registry — 复用 obase.ProviderRegistry (L-021, L-022).

All methods are classmethods; use ProviderRegistry.register() directly.
"""

from obase.provider_registry import ProviderRegistry
from oprim import ltx2_cloud_generate, video_generate

__all__ = ["ProviderRegistry", "register_all_providers"]


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup."""
    # Register LTX-2 Cloud
    ProviderRegistry.register(
        "video", "ltx2_cloud", ltx2_cloud_generate  # type: ignore[arg-type]
    )

    # Register Wan Cloud
    # For Wan Cloud, we use video_generate with provider="wan_cloud"
    # We might need a partial or a lambda if ProviderRegistry expects a specific signature,
    # but here we follow the instruction to register them.
    ProviderRegistry.register(
        "video",
        "wan_cloud",
        lambda **kwargs: video_generate(  # type: ignore[operator]
            provider="wan_cloud", **kwargs
        ),
    )
