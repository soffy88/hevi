from dataclasses import dataclass
from typing import Any, Literal

from hevi.core.config import settings
from hevi.cost.pricing_table import get_ltx2_price_per_second, get_pricing_table
from hevi.video import get_duration_config
from hevi.video.quality_profile import (
    DEFAULT_QUALITY,
    get_ltx2_pricing_key,
    get_quality_cost_multiplier,
)


@dataclass
class CostEstimate:
    video_cost_usd: float
    audio_cost_usd: float
    total_usd: float
    breakdown: dict[str, Any]
    estimated_credits: int


async def estimate_cost(
    *,
    duration_archetype: str,
    video_provider: str,
    audio_provider: str,
    num_characters: int = 1,
    quality: str = DEFAULT_QUALITY,
    ltx2_tier: Literal["fast", "pro"] = "fast",
) -> CostEstimate:
    """Estimate total cost before running a long video generation task.

    For ltx2_cloud, cost is derived from the 2D fal.ai pricing table
    (tier × resolution) rather than a flat rate.  For other providers
    a flat rate with a quality multiplier is applied.
    """
    duration_cfg = get_duration_config(duration_archetype)
    total_seconds = float(duration_cfg["target_s"])
    pricing = get_pricing_table()

    # 1. Video cost
    video_cost = 0.0
    breakdown_extra: dict[str, Any] = {}
    if video_provider == "ltx2_cloud":
        pricing_key = get_ltx2_pricing_key(quality)
        price_per_s = get_ltx2_price_per_second(ltx2_tier, pricing_key)
        video_cost = total_seconds * price_per_s
        breakdown_extra = {"ltx2_tier": ltx2_tier, "ltx2_pricing_key": pricing_key}
    else:
        v_pricing = pricing.get(video_provider, {"unit": "per_second", "price_usd": 0.05})
        quality_multiplier = get_quality_cost_multiplier(quality)
        if v_pricing["unit"] == "per_second":
            video_cost = total_seconds * v_pricing["price_usd"] * quality_multiplier
        elif v_pricing["unit"] == "per_minute":
            video_cost = (total_seconds / 60.0) * v_pricing["price_usd"] * quality_multiplier
        breakdown_extra = {"quality_multiplier": quality_multiplier}

    # 2. Audio cost — 10% more per extra character for complexity
    a_pricing = pricing.get(audio_provider, {"unit": "per_minute", "price_usd": 0.0})
    audio_seconds = total_seconds * (1.0 + (num_characters - 1) * 0.1)
    audio_cost = 0.0
    if a_pricing["unit"] == "per_second":
        audio_cost = audio_seconds * a_pricing["price_usd"]
    elif a_pricing["unit"] == "per_minute":
        audio_cost = (audio_seconds / 60.0) * a_pricing["price_usd"]

    total_usd = video_cost + audio_cost

    return CostEstimate(
        video_cost_usd=video_cost,
        audio_cost_usd=audio_cost,
        total_usd=total_usd,
        breakdown={
            video_provider: video_cost,
            audio_provider: audio_cost,
            "duration_s": total_seconds,
            "quality": quality,
            **breakdown_extra,
        },
        estimated_credits=int(total_usd * settings.credits_per_usd),
    )
