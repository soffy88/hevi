"""Tests for order_flow_imbalance."""

import numpy as np
import pytest

from oskill.microstructure.order_flow import order_flow_imbalance


def test_ofi_volume_basic():
    """Volume method returns array of correct shape."""
    bid_v = np.array([100.0, 80.0, 120.0])
    ask_v = np.array([60.0, 90.0, 40.0])
    ofi = order_flow_imbalance(bid_v, ask_v)
    assert ofi.shape == (3,)


def test_ofi_volume_normalized_bounds():
    """Volume method output is in [-1, 1]."""
    rng = np.random.default_rng(42)
    bid_v = rng.uniform(1, 200, 100)
    ask_v = rng.uniform(1, 200, 100)
    ofi = order_flow_imbalance(bid_v, ask_v)
    assert np.all(ofi >= -1.0)
    assert np.all(ofi <= 1.0)


def test_ofi_volume_sign():
    """Positive when bid > ask; negative when ask > bid."""
    bid_v = np.array([200.0, 50.0])
    ask_v = np.array([50.0, 200.0])
    ofi = order_flow_imbalance(bid_v, ask_v)
    assert ofi[0] > 0  # bid dominates
    assert ofi[1] < 0  # ask dominates


def test_ofi_volume_zero_total():
    """Zero total volume yields OFI = 0."""
    bid_v = np.array([0.0, 100.0])
    ask_v = np.array([0.0, 50.0])
    ofi = order_flow_imbalance(bid_v, ask_v)
    assert ofi[0] == 0.0


def test_ofi_window_rolling():
    """Window parameter returns rolling sum of raw imbalance."""
    bid_v = np.ones(10) * 100
    ask_v = np.ones(10) * 60
    ofi = order_flow_imbalance(bid_v, ask_v, window=3)
    assert ofi.shape == (10,)
    # Each element is rolling sum of raw (bid - ask) = 40 per tick
    # At index 0: 40; at index 1: 80; at index 2+: 120
    assert ofi[0] == pytest.approx(40.0)
    assert ofi[2] == pytest.approx(120.0)
    assert ofi[9] == pytest.approx(120.0)


def test_ofi_price_weighted_requires_prices():
    """price_weighted method raises ValueError without price arrays."""
    bid_v = np.array([100.0, 80.0])
    ask_v = np.array([60.0, 90.0])
    with pytest.raises(ValueError, match="bid_prices"):
        order_flow_imbalance(bid_v, ask_v, method="price_weighted")


def test_ofi_price_weighted_basic():
    """price_weighted method returns array of same length."""
    rng = np.random.default_rng(10)
    n = 20
    bid_v = rng.uniform(50, 150, n)
    ask_v = rng.uniform(50, 150, n)
    bid_p = 100 + np.cumsum(rng.normal(0, 0.05, n))
    ask_p = bid_p + 0.01
    ofi = order_flow_imbalance(
        bid_v, ask_v, bid_prices=bid_p, ask_prices=ask_p, method="price_weighted"
    )
    assert ofi.shape == (n,)


def test_ofi_invalid_method():
    """Unknown method raises ValueError."""
    with pytest.raises(ValueError, match="Unknown method"):
        order_flow_imbalance(np.ones(5), np.ones(5), method="bad")


def test_ofi_equal_volumes():
    """Equal bid and ask volumes yield zero OFI (volume method)."""
    v = np.array([100.0, 200.0, 50.0])
    ofi = order_flow_imbalance(v, v)
    np.testing.assert_array_equal(ofi, np.zeros(3))
