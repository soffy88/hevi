"""Tests for Cartea-Jaimungal market making model."""

from __future__ import annotations

import pytest

from oskill.market_making.cartea_jaimungal import cartea_jaimungal_optimal_quotes


def test_cj_basic():
    r = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    assert "bid" in r and "ask" in r


def test_cj_bid_less_than_ask():
    r = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    assert r["bid"] < r["ask"]


def test_cj_positive_drift_adjusts_reservation():
    r_nodrift = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01, drift=0.0)
    r_drift = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01, drift=1.0)
    assert r_drift["reservation_price"] != r_nodrift["reservation_price"]


def test_cj_adverse_selection_widens_spread():
    r_no_ofi = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    r_ofi = cartea_jaimungal_optimal_quotes(100.0, 0, 0.8, volatility=0.01)
    assert r_ofi["adverse_selection_premium"] > r_no_ofi["adverse_selection_premium"]


def test_cj_inventory_aggression():
    r_high_inv = cartea_jaimungal_optimal_quotes(100.0, 50, 0.0, volatility=0.01)
    r_low_inv = cartea_jaimungal_optimal_quotes(100.0, 5, 0.0, volatility=0.01)
    assert r_high_inv["inventory_aggression"] > r_low_inv["inventory_aggression"]


def test_cj_returns_baseline_as_quotes():
    r = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    assert "as_baseline_bid" in r and "as_baseline_ask" in r


def test_cj_zero_ofi_zero_as_premium():
    r = cartea_jaimungal_optimal_quotes(
        100.0, 0, 0.0, volatility=0.01, adverse_selection_aversion=0.5
    )
    assert abs(r["adverse_selection_premium"]) < 1e-10


def test_cj_fingerprint_string():
    r = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    assert isinstance(r["fingerprint"], str) and len(r["fingerprint"]) == 64


def test_cj_higher_vol_wider_spread():
    r_low = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.01)
    r_high = cartea_jaimungal_optimal_quotes(100.0, 0, 0.0, volatility=0.05)
    assert r_high["ask"] - r_high["bid"] > r_low["ask"] - r_low["bid"]


def test_cj_invalid_raises():
    with pytest.raises(ValueError):
        cartea_jaimungal_optimal_quotes(-100.0, 0, 0.0, volatility=0.01)
