import logging
from typing import Any

from obase.cost_tracker import CostTracker, PricingEntry, PricingTable

from hevi.cost.pricing_table import get_pricing_table

logger = logging.getLogger(__name__)


def create_hevi_tracker(budget_usd: float | None = None) -> CostTracker:
    """Create a CostTracker pre-populated with hevi pricing."""
    pricing = get_pricing_table()
    entries = []
    
    for provider, p_info in pricing.items():
        # Mapping to obase format
        # category is 'video' or 'audio'
        category = "video" if "cloud" in provider or provider in ("ltx2", "wan") else "audio"
        if provider in ("vibevoice", "duix"):
            category = "audio"
            
        entries.append(PricingEntry(
            category=category,
            provider=provider,
            model_or_tier="default",
            unit=p_info["unit"],
            price_usd=p_info["price_usd"]
        ))
        
    table = PricingTable(entries=entries)
    return CostTracker(pricing_table=table, budget_usd=budget_usd)


class HeviCostTracker:
    """Convenience wrapper for actual cost tracking in hevi."""
    
    def __init__(self, budget_usd: float | None = None):
        self.internal = create_hevi_tracker(budget_usd=budget_usd)
        
    def record_video(self, provider: str, duration_s: float) -> float:
        return self.internal.record(
            category="video",
            provider=provider,
            model_or_tier="default",
            unit="per_second",
            quantity=duration_s
        )

    def record_audio(self, provider: str, duration_m: float) -> float:
        return self.internal.record(
            category="audio",
            provider=provider,
            model_or_tier="default",
            unit="per_minute",
            quantity=duration_m
        )
        
    def get_summary(self) -> dict[str, Any]:
        return self.internal.summary()
    
    @property
    def total_usd(self) -> float:
        return float(self.internal.total_usd)
