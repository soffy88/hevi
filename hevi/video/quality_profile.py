from dataclasses import dataclass

__all__ = [
    "ASPECT_RATIOS",
    "DEFAULT_ASPECT_RATIO",
    "DEFAULT_QUALITY",
    "QUALITY_PROFILES",
    "QualityProfile",
    "get_ltx2_pricing_key",
    "get_quality_cost_multiplier",
    "get_quality_profile",
    "resolve_resolution",
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


# 画幅:档位定清晰度(短边像素),画幅定朝向。此前分辨率全 portrait → 成片锁死 9:16;
# 有了它,横屏/方屏内容才做得了。
ASPECT_RATIOS = ("9:16", "16:9", "1:1")
DEFAULT_ASPECT_RATIO = "9:16"


def resolve_resolution(
    name: str = DEFAULT_QUALITY, aspect_ratio: str = DEFAULT_ASPECT_RATIO
) -> tuple[int, int]:
    """按画幅把质量档分辨率重排成 (w, h)。9:16 竖 / 16:9 横 / 1:1 方;未知画幅回退 9:16。"""
    try:
        w, h = get_quality_profile(name).resolution
    except ValueError:
        w, h = get_quality_profile(DEFAULT_QUALITY).resolution
    short, long = min(w, h), max(w, h)
    if aspect_ratio == "16:9":
        return (long, short)
    if aspect_ratio == "1:1":
        return (short, short)
    return (short, long)  # 9:16 默认(含未知值)
