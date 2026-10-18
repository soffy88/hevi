"""Shared Avellaneda-Stoikov base math."""

from __future__ import annotations

import math


def _as_reservation_price(
    mid: float, inventory: int, risk_aversion: float, sigma: float, t: float
) -> float:
    """r(s,q,t) = s - q * gamma * sigma^2 * T"""
    return mid - inventory * risk_aversion * sigma**2 * t


def _as_optimal_spread(risk_aversion: float, sigma: float, t: float, intensity_k: float) -> float:
    """delta = gamma * sigma^2 * T + (2/gamma) * log(1 + gamma/k)"""
    return risk_aversion * sigma**2 * t + (2.0 / risk_aversion) * math.log(
        1.0 + risk_aversion / intensity_k
    )
