"""Tests for Avellaneda-Stoikov market making model."""

from __future__ import annotations

import math

import numpy as np
import pytest

from oskill.market_making.avellaneda_stoikov import avellaneda_stoikov_quotes


def test_as_basic():
    r = avellaneda_stoikov_quotes(100.0, 0, volatility=0.01, time_to_horizon=1.0)
    assert "bid" in r and "ask" in r


def test_as_bid_less_than_ask():
    r = avellaneda_stoikov_quotes(100.0, 0, volatility=0.01, time_to_horizon=1.0)
    assert r["bid"] < r["ask"]


def test_as_spread_positive():
    r = avellaneda_stoikov_quotes(100.0, 0, volatility=0.02, time_to_horizon=0.5)
    assert r["optimal_spread"] > 0


def test_as_zero_inventory_symmetric():
    r = avellaneda_stoikov_quotes(100.0, 0, volatility=0.01, time_to_horizon=1.0)
    # Zero inventory: bid and ask symmetric around mid
    np.testing.assert_allclose((r["bid"] + r["ask"]) / 2, 100.0, rtol=1e-6)


def test_as_positive_inventory_lower_reservation():
    # Long inventory: market maker wants to sell → reservation < mid
    r = avellaneda_stoikov_quotes(100.0, 10, volatility=0.01, time_to_horizon=1.0)
    assert r["reservation_price"] < 100.0


def test_as_negative_inventory_higher_reservation():
    # Short inventory: market maker wants to buy → reservation > mid
    r = avellaneda_stoikov_quotes(100.0, -10, volatility=0.01, time_to_horizon=1.0)
    assert r["reservation_price"] > 100.0


def test_as_higher_vol_wider_spread():
    r_low = avellaneda_stoikov_quotes(100.0, 0, volatility=0.01, time_to_horizon=1.0)
    r_high = avellaneda_stoikov_quotes(100.0, 0, volatility=0.05, time_to_horizon=1.0)
    assert r_high["optimal_spread"] > r_low["optimal_spread"]


def test_as_inventory_limit_pause():
    r = avellaneda_stoikov_quotes(
        100.0, 10, volatility=0.01, time_to_horizon=1.0, inventory_limit=5
    )
    assert r["should_pause_quoting"]


def test_as_no_inventory_limit_no_pause():
    r = avellaneda_stoikov_quotes(
        100.0, 10, volatility=0.01, time_to_horizon=1.0, inventory_limit=None
    )
    assert not r["should_pause_quoting"]


def test_as_invalid_mid_raises():
    with pytest.raises(ValueError):
        avellaneda_stoikov_quotes(-100.0, 0, volatility=0.01, time_to_horizon=1.0)


@pytest.mark.academic_reference
def test_as_formula_exact():
    # Verify formula from Avellaneda & Stoikov 2008
    mid, q, gamma, sigma, T, k = 100.0, 5, 0.1, 0.01, 1.0, 1.5
    expected_r = mid - q * gamma * sigma**2 * T
    expected_delta = gamma * sigma**2 * T + (2 / gamma) * math.log(1 + gamma / k)
    r = avellaneda_stoikov_quotes(
        mid, q, volatility=sigma, time_to_horizon=T, risk_aversion=gamma, intensity_k=k
    )
    np.testing.assert_allclose(r["reservation_price"], expected_r, rtol=1e-10)
    np.testing.assert_allclose(r["optimal_spread"], expected_delta, rtol=1e-10)
