from dataclasses import dataclass

from obase.provider_registry import ProviderRegistry

__all__ = ["CapabilityError", "ProviderLimits", "PROVIDER_LIMITS", "validate_request"]


class CapabilityError(ValueError):
    """Raised when a request exceeds a provider's declared capability."""


@dataclass(frozen=True)
class ProviderLimits:
    modes: frozenset[str]
    max_resolution: tuple[int, int]  # (width, height)
    max_duration_s: float
    fps_options: frozenset[int]


PROVIDER_LIMITS: dict[str, ProviderLimits] = {
    "ltx2_cloud": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(2160, 3840),
        max_duration_s=300.0,
        fps_options=frozenset({24, 30}),
    ),
    "wan_cloud": ProviderLimits(
        modes=frozenset({"t2v", "i2v"}),
        max_resolution=(1080, 1920),
        max_duration_s=120.0,
        fps_options=frozenset({24}),
    ),
}


async def validate_request(
    *,
    provider: str,
    mode: str,
    resolution: tuple[int, int],
    duration_s: float,
    fps: int,
) -> None:
    """Validate a video-generation request against provider capability limits.

    Checks obase-registered capability tags first; falls back to PROVIDER_LIMITS.
    Raises CapabilityError on any violation so invalid requests are caught before
    consuming an API call.
    """
    if provider not in PROVIDER_LIMITS:
        raise CapabilityError(f"Unknown provider: {provider!r}")

    limits = PROVIDER_LIMITS[provider]

    # Use obase-registered tags for mode check when available.
    registered_caps = ProviderRegistry.capabilities("video", provider)
    if registered_caps:
        if mode not in registered_caps:
            raise CapabilityError(
                f"Provider {provider!r} registered capabilities {registered_caps!r} "
                f"do not include mode {mode!r}"
            )
    elif mode not in limits.modes:
        raise CapabilityError(
            f"Provider {provider!r} does not support mode {mode!r} "
            f"(supported: {set(limits.modes)})"
        )

    w, h = resolution
    max_w, max_h = limits.max_resolution
    if w > max_w or h > max_h:
        raise CapabilityError(
            f"Resolution {resolution} exceeds {provider!r} max {limits.max_resolution}"
        )

    if duration_s > limits.max_duration_s:
        raise CapabilityError(
            f"Duration {duration_s}s exceeds {provider!r} max {limits.max_duration_s}s"
        )

    if fps not in limits.fps_options:
        raise CapabilityError(
            f"fps={fps} not in {provider!r} fps_options {set(limits.fps_options)}"
        )
