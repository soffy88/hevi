"""L2 provider registry — 复用 obase.ProviderRegistry (L-021, L-022).

All methods are classmethods; use ProviderRegistry.register() directly.
"""

from obase.provider_registry import ProviderRegistry

__all__ = ["ProviderRegistry", "register_all_providers"]


def register_all_providers() -> None:
    """Register all L2 kernel providers at startup.

    Populated in later batches as LTX-2 / Wan / VibeVoice / Duix providers are wired in.
    Example:
        ProviderRegistry.register("video", "ltx2", ltx2_generate)
        ProviderRegistry.register("video", "wan", wan_generate)
    """
