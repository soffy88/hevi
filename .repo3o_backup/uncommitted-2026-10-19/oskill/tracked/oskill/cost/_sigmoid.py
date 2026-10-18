"""Sigmoid market impact model for crypto perpetual and spot markets.

Saturates at max_impact_bps as participation → 1.
Smooth derivative (no kink at p=0 like sqrt law).
Vol-adjusted: high-vol assets have a lower half-saturation point
(they attract more impact per unit participation).
"""

from __future__ import annotations

import math


def crypto_market_impact_sigmoid(
    notional_usd: float,
    daily_volume_usd: float,
    realized_vol_30d: float = 0.6,
    max_impact_bps: float = 200.0,
    **_extra,
) -> dict:
    """Sigmoid market impact model for crypto.

    Parameters
    ----------
    notional_usd:
        Order size in USD.
    daily_volume_usd:
        Average daily volume of the instrument in USD.
        Floored at 1e6 to avoid division by near-zero on illiquid assets.
    realized_vol_30d:
        30-day realized annualised volatility (e.g. 0.6 = 60%).
        Scales the half-saturation participation point k:
        low-vol (BTC ~0.4) → k≈0.05; high-vol (1.5+) → k≈0.013.
    max_impact_bps:
        Asymptotic ceiling in basis points as participation → 1.
    **_extra:
        Absorbs legacy YAML params (sigmoid_center, sigmoid_scale) silently.

    Returns
    -------
    dict with keys:
        impact_bps        — estimated market impact in bps
        participation     — notional / daily_volume
        model             — model identifier string
        params            — params used for this call
    """
    adv = max(daily_volume_usd, 1_000_000.0)
    participation = notional_usd / adv

    # Half-saturation participation:
    # baseline k=0.05 (5% ADV → 63% of max_impact at ref vol 0.4)
    # high-vol assets saturate faster (lower k)
    vol_ratio = max(realized_vol_30d / 0.4, 1.0)
    k = 0.05 / vol_ratio

    impact_bps = max_impact_bps * (1.0 - math.exp(-participation / k))

    return {
        "impact_bps": impact_bps,
        "participation": participation,
        "model": "crypto_market_impact_sigmoid_v1",
        "params": {
            "max_impact_bps": max_impact_bps,
            "half_sat_participation_k": k,
            "realized_vol_30d_input": realized_vol_30d,
        },
    }
