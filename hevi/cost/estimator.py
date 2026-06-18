"""hevi cost estimator — delegates to obase.CostTracker.estimate_steps."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from obase.cost_tracker import CostBreakdown, CostTracker, PricingEntry, PricingTable, StepUsage

from hevi.core.config import settings
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
    per_step: CostBreakdown | None = None


def _build_estimation_tracker(
    *,
    video_provider: str,
    video_price_per_s: float,
    audio_provider: str,
    audio_price: float,
    audio_unit: str,
) -> CostTracker:
    """Create a single-use CostTracker for estimation.

    Registers under category='default' because estimate_steps hardcodes that
    in its PricingTable lookup (StepUsage.category is metadata-only in v0.15.10).
    """
    return CostTracker(
        pricing_table=PricingTable(entries=[
            PricingEntry(
                category="default",
                provider=video_provider,
                model_or_tier="default",
                unit="per_second",
                price_usd=video_price_per_s,
            ),
            PricingEntry(
                category="default",
                provider=audio_provider,
                model_or_tier="default",
                unit=audio_unit,
                price_usd=audio_price,
            ),
        ]),
        strict_pricing=False,
    )


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

    Delegates per-step multiplication and CostBreakdown aggregation to
    obase.CostTracker.estimate_steps (真下沉 — obase v0.15.10+).

    For ltx2_cloud the 2D (tier × resolution) price is resolved here;
    quality multiplier is applied for non-ltx2 providers.
    """
    from hevi.cost.pricing_table import get_ltx2_price_per_second, get_pricing_table

    duration_cfg = get_duration_config(duration_archetype)
    total_s = float(duration_cfg["target_s"])
    pricing = get_pricing_table()

    # 1. Effective video price per second
    breakdown_extra: dict[str, Any] = {}
    if video_provider == "ltx2_cloud":
        pricing_key = get_ltx2_pricing_key(quality)
        video_price_per_s = get_ltx2_price_per_second(ltx2_tier, pricing_key)
        breakdown_extra = {"ltx2_tier": ltx2_tier, "ltx2_pricing_key": pricing_key}
    else:
        v_info = pricing.get(video_provider, {"unit": "per_second", "price_usd": 0.05})
        quality_mult = get_quality_cost_multiplier(quality)
        raw = v_info["price_usd"] * quality_mult
        if v_info["unit"] == "per_minute":
            raw = raw / 60.0
        video_price_per_s = raw
        breakdown_extra = {"quality_multiplier": quality_mult}

    # 2. Audio: adjust usage for multi-character, normalise unit
    audio_s = total_s * (1.0 + (num_characters - 1) * 0.1)
    a_info = pricing.get(audio_provider, {"unit": "per_minute", "price_usd": 0.0})
    audio_price = a_info["price_usd"]
    audio_unit = a_info["unit"]
    audio_usage = audio_s / 60.0 if audio_unit == "per_minute" else audio_s

    # 3. Delegate to obase.CostTracker.estimate_steps
    tracker = _build_estimation_tracker(
        video_provider=video_provider,
        video_price_per_s=video_price_per_s,
        audio_provider=audio_provider,
        audio_price=audio_price,
        audio_unit=audio_unit,
    )
    steps = [
        StepUsage(
            step="video",
            provider=video_provider,
            usage=total_s,
            unit="per_second",
            category="video",
        ),
        StepUsage(
            step="audio",
            provider=audio_provider,
            usage=audio_usage,
            unit=audio_unit,
            category="audio",
        ),
    ]
    per_step = tracker.estimate_steps(steps)  # type: ignore[attr-defined]

    video_cost = float(per_step.per_step.get("video", Decimal("0")))
    audio_cost = float(per_step.per_step.get("audio", Decimal("0")))

    return CostEstimate(
        video_cost_usd=video_cost,
        audio_cost_usd=audio_cost,
        total_usd=float(per_step.total),
        breakdown={
            video_provider: video_cost,
            audio_provider: audio_cost,
            "duration_s": total_s,
            "quality": quality,
            **breakdown_extra,
        },
        estimated_credits=int(float(per_step.total) * settings.credits_per_usd),
        per_step=per_step,
    )
