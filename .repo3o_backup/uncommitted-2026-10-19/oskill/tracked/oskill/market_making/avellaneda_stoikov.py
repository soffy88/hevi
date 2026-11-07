"""Avellaneda-Stoikov (2008) market making model."""

from __future__ import annotations

from typing import Any

import oprim

from oskill.market_making._base import _as_optimal_spread, _as_reservation_price


def avellaneda_stoikov_quotes(
    mid_price: float,
    inventory: int,
    *,
    volatility: float,
    time_to_horizon: float,
    risk_aversion: float = 0.1,
    intensity_k: float = 1.5,
    intensity_A: float = 140.0,
    inventory_limit: int | None = None,
) -> dict[str, Any]:
    """Compute optimal bid/ask quotes using the Avellaneda-Stoikov (2008) model.

    Derives the reservation price and optimal spread from stochastic control theory
    for a market maker facing inventory risk.

    Mathematical reference: Avellaneda & Stoikov (2008), "High-frequency trading in a
    limit order book", Quantitative Finance 8(3), 217-224.

    Parameters
    ----------
    mid_price : float
        Current mid-market price (must be > 0).
    inventory : int
        Current net inventory position (positive = long, negative = short).
    volatility : float
        Price volatility per unit time (>= 0). In HFT usage, units are
        price per sqrt(second) with time_to_horizon in seconds.
    time_to_horizon : float
        Remaining time horizon T (>= 0).
    risk_aversion : float
        Risk aversion parameter gamma (> 0). Default 0.1.
    intensity_k : float
        Order arrival intensity rate k (> 0). Default 1.5.
    intensity_A : float
        Baseline order arrival intensity A. Default 140.0.
    inventory_limit : int or None
        If set, pause quoting when abs(inventory) >= inventory_limit.

    Returns
    -------
    dict with keys:
        'bid': float
        'ask': float
        'reservation_price': float
        'optimal_spread': float
        'half_spread_above_mid': float
        'half_spread_below_mid': float
        'should_pause_quoting': bool
        'fingerprint': str — SHA-256 of canonical JSON of key quote values
    """
    if mid_price <= 0:
        raise ValueError(f"mid_price must be > 0, got {mid_price}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if time_to_horizon < 0:
        raise ValueError(f"time_to_horizon must be >= 0, got {time_to_horizon}")
    if risk_aversion <= 0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion}")
    if intensity_k <= 0:
        raise ValueError(f"intensity_k must be > 0, got {intensity_k}")

    reservation_price = _as_reservation_price(
        mid_price, inventory, risk_aversion, volatility, time_to_horizon
    )
    optimal_spread = _as_optimal_spread(risk_aversion, volatility, time_to_horizon, intensity_k)

    bid = reservation_price - optimal_spread / 2.0
    ask = reservation_price + optimal_spread / 2.0

    half_spread_above_mid = ask - mid_price
    half_spread_below_mid = mid_price - bid

    should_pause_quoting = (inventory_limit is not None) and (abs(inventory) >= inventory_limit)

    fp = oprim.sha256_hash(
        oprim.canonical_json(
            {"ask": ask, "bid": bid, "reservation": reservation_price, "spread": optimal_spread}
        )
    )

    return {
        "bid": bid,
        "ask": ask,
        "reservation_price": reservation_price,
        "optimal_spread": optimal_spread,
        "half_spread_above_mid": half_spread_above_mid,
        "half_spread_below_mid": half_spread_below_mid,
        "should_pause_quoting": should_pause_quoting,
        "fingerprint": fp,
    }
