from dataclasses import dataclass

__all__ = [
    "QualityProfile",
    "QUALITY_PROFILES",
    "DEFAULT_QUALITY",
    "get_quality_profile",
    "get_quality_cost_multiplier",
    "get_ltx2_pricing_key",
]


@dataclass(frozen=True)
class QualityProfile:
    """Video quality parameters for a named tier."""

    resolution: tuple[int, int]  # (width, height), portrait-first per hevi convention
    fps: int
    bitrate_kbps: int | None
    ltx2_pricing_key: str = "1080p"  # fal.ai billing resolution bucket


QUALITY_PROFILES: dict[str, QualityProfile] = {
    "standard": QualityProfile(
        resolution=(720, 1280), fps=24, bitrate_kbps=2500, ltx2_pricing_key="1080p"
    ),
    "high": QualityProfile(
        resolution=(1080, 1920), fps=30, bitrate_kbps=5000, ltx2_pricing_key="1080p"
    ),
    "ultra": QualityProfile(
        resolution=(2160, 3840), fps=30, bitrate_kbps=12000, ltx2_pricing_key="2160p"
    ),
}

# Cost multiplier relative to "standard" — ultra requires more compute/bandwidth.
_QUALITY_COST_MULTIPLIER: dict[str, float] = {
    "standard": 1.0,
    "high": 1.5,
    "ultra": 2.5,
}

DEFAULT_QUALITY = "standard"


def get_quality_profile(name: str = DEFAULT_QUALITY) -> QualityProfile:
    if name not in QUALITY_PROFILES:
        raise ValueError(f"Unknown quality profile: {name!r}. Valid: {list(QUALITY_PROFILES)}")
    return QUALITY_PROFILES[name]


def get_quality_cost_multiplier(name: str = DEFAULT_QUALITY) -> float:
    return _QUALITY_COST_MULTIPLIER.get(name, 1.0)


def get_ltx2_pricing_key(name: str = DEFAULT_QUALITY) -> str:
    """Return the fal.ai billing resolution key for a quality profile name."""
    return get_quality_profile(name).ltx2_pricing_key
