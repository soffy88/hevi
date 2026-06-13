from typing import Any

from hevi.core.config import settings


def get_pricing_table() -> dict[str, dict[str, Any]]:
    """Get current provider pricing from settings.
    
    Local providers (vibevoice, duix) are currently free (GPU cost handled separately).
    """
    return {
        "ltx2_cloud": {"unit": "per_second", "price_usd": settings.ltx2_price_usd},
        "wan_cloud": {"unit": "per_second", "price_usd": settings.wan_price_usd},
        "vibevoice": {"unit": "per_minute", "price_usd": 0.0},
        "duix": {"unit": "per_minute", "price_usd": 0.0},
    }
