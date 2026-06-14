from typing import Any

from hevi.core.config import settings

# fal.ai LTX-2 真实二维单价 (tier × resolution), 美元/秒
# Source: fal.ai pricing page, calibrated 2026-06
LTX2_PRICING: dict[str, dict[str, float]] = {
    "fast": {
        "1080p": 0.04,
        "1440p": 0.08,
        "2160p": 0.16,
    },
    "pro": {
        "1080p": 0.06,
        "1440p": 0.12,
        "2160p": 0.24,
    },
}

# video_element_edit (retake) 端点单价, 美元/秒
LTX2_RETAKE_PER_SECOND: float = 0.10

DEFAULT_LTX2_TIER: str = "fast"

# fal.ai endpoint URLs — switched via M1 config dict key "FAL_BASE_URL".
# NOTE: M1 ltx2_cloud_generate has no tier param; we pass the endpoint via config.
# Pro URL is a placeholder — confirm actual endpoint with fal.ai before enabling.
LTX2_ENDPOINTS: dict[str, str] = {
    "fast": "https://fal.run/fal-ai/ltx-video",
    "pro": "https://fal.run/fal-ai/ltx-video-pro",  # placeholder; verify with fal.ai
}


def get_ltx2_price_per_second(tier: str, resolution: str) -> float:
    """Return fal.ai LTX-2 price per second for (tier, resolution_key) pair."""
    tier_table = LTX2_PRICING.get(tier, LTX2_PRICING[DEFAULT_LTX2_TIER])
    return tier_table.get(resolution, tier_table["1080p"])


def get_pricing_table() -> dict[str, dict[str, Any]]:
    """Get current provider pricing table.

    ltx2_cloud: price_usd is the Fast-1080p default; use pricing_2d for
    resolution-aware billing or call get_ltx2_price_per_second() directly.
    """
    return {
        "ltx2_cloud": {
            "unit": "per_second",
            "price_usd": get_ltx2_price_per_second(DEFAULT_LTX2_TIER, "1080p"),
            "pricing_2d": LTX2_PRICING,
        },
        "wan_cloud": {"unit": "per_second", "price_usd": settings.wan_price_usd},
        "vibevoice": {"unit": "per_minute", "price_usd": 0.0},
        "duix": {"unit": "per_minute", "price_usd": 0.0},
    }
