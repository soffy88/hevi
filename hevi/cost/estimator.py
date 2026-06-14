from dataclasses import dataclass
from typing import Any

from hevi.core.config import settings
from hevi.cost.pricing_table import get_pricing_table
from hevi.video import get_duration_config
from hevi.video.quality_profile import DEFAULT_QUALITY, get_quality_cost_multiplier


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
) -> CostEstimate:
    """Estimate total cost before running a long video generation task.

    The ``quality`` tier scales video cost: ultra quality requires higher compute
    and bitrate budget, so its multiplier (2.5×) is applied to the raw video cost.
    Audio cost is unaffected by quality.
    """

    duration_cfg = get_duration_config(duration_archetype)
    total_seconds = float(duration_cfg["target_s"])
    pricing = get_pricing_table()
    quality_multiplier = get_quality_cost_multiplier(quality)

    # 1. Video Cost (scaled by quality tier)
    v_pricing = pricing.get(video_provider, {"unit": "per_second", "price_usd": 0.05})
    video_cost = 0.0
    if v_pricing["unit"] == "per_second":
        video_cost = total_seconds * v_pricing["price_usd"] * quality_multiplier
    elif v_pricing["unit"] == "per_minute":
        video_cost = (total_seconds / 60.0) * v_pricing["price_usd"] * quality_multiplier

    # 2. Audio Cost
    # Simple logic: base duration + small overhead per character for complexity
    # Realistically, vibevoice/duix might have different pricing if they weren't local
    a_pricing = pricing.get(audio_provider, {"unit": "per_minute", "price_usd": 0.0})

    # 10% more audio per extra char
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
            "quality_multiplier": quality_multiplier,
        },
        estimated_credits=int(total_usd * settings.credits_per_usd),
    )
