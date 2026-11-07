"""Tests for oskill.signal_detection: adx, cusum_detector, platt_calibration."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.signal_detection import adx, cusum_detector, platt_calibration

# ─── ADX tests ───────────────────────────────────────────────────────────────


def _make_ohlc(n: int = 30, trend: float = 0.0, rng_seed: int = 42):
    """Create synthetic OHLC arrays."""
    rng = np.random.default_rng(rng_seed)
    closes = np.cumsum(rng.normal(trend, 0.5, n)) + 100
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    return highs, lows, closes


def test_adx_returns_float():
    """adx() should return a float."""
    highs, lows, closes = _make_ohlc(40)
    result = adx(highs, lows, closes, period=14)
    assert isinstance(result, float)


def test_adx_too_few_bars_raises():
    """Fewer than period+1 bars should raise ValueError."""
    highs, lows, closes = _make_ohlc(10)
    with pytest.raises(ValueError, match="at least"):
        adx(highs, lows, closes, period=14)


def test_adx_trending_high_value():
    """Monotone uptrend → ADX > 20."""
    n = 50
    closes = np.linspace(100, 200, n)
    highs = closes + 1.0
    lows = closes - 0.5
    result = adx(highs, lows, closes, period=14)
    assert result > 20, f"Expected ADX>20 for trending data, got {result:.2f}"


def test_adx_flat_market_low_value():
    """Constant prices → ADX should be 0 or very low."""
    n = 40
    closes = np.full(n, 100.0)
    highs = closes + 0.01
    lows = closes - 0.01
    result = adx(highs, lows, closes, period=14)
    assert result < 5.0, f"Expected ADX<5 for flat market, got {result:.2f}"


def test_adx_result_in_valid_range():
    """ADX should be in [0, 100]."""
    highs, lows, closes = _make_ohlc(60, trend=0.1)
    result = adx(highs, lows, closes, period=14)
    assert 0.0 <= result <= 100.0


# ─── CUSUM tests ──────────────────────────────────────────────────────────────


def test_cusum_returns_dict_keys():
    """cusum_detector must return dict with pos_cusum, neg_cusum, signals."""
    z = np.zeros(20)
    result = cusum_detector(z, threshold=2.0)
    assert set(result.keys()) == {"pos_cusum", "neg_cusum", "signals"}
    assert isinstance(result["signals"], list)
    assert len(result["pos_cusum"]) == 20


def test_cusum_no_signals_for_white_noise():
    """Small z_scores with high threshold → no signals."""
    rng = np.random.default_rng(0)
    z = rng.normal(0, 0.1, 100)
    result = cusum_detector(z, threshold=10.0)
    assert result["signals"] == []


def test_cusum_detects_mean_shift():
    """Step function (z = 0 then z = 5) → signals list non-empty."""
    z = np.concatenate([np.zeros(20), np.full(20, 5.0)])
    result = cusum_detector(z, threshold=2.0)
    assert len(result["signals"]) > 0


def test_cusum_reset_after_signal():
    """After a signal at index i, pos_cusum[i] should be 0."""
    z = np.full(30, 3.0)  # each step accumulates +3
    result = cusum_detector(z, threshold=5.0)
    signals = result["signals"]
    assert len(signals) > 0
    for sig_idx in signals:
        assert result["pos_cusum"][sig_idx] == 0.0 or result["neg_cusum"][sig_idx] == 0.0


def test_cusum_drift_reduces_sensitivity():
    """High drift → fewer signals than low drift for same data."""
    rng = np.random.default_rng(7)
    z = rng.normal(1.5, 0.3, 200)
    r_low_drift = cusum_detector(z, threshold=2.0, drift=0.0)
    r_high_drift = cusum_detector(z, threshold=2.0, drift=1.4)
    assert len(r_high_drift["signals"]) <= len(r_low_drift["signals"])


@pytest.mark.academic_reference
def test_cusum_page_1954():
    """Page (1954): for z_t = threshold + 0.1 every step, first signal at t=1.

    Reference: Page, E.S. (1954). Biometrika.
    The positive CUSUM at time 1 = max(0, z_1 - drift) = threshold + 0.1 > threshold.
    So a signal should be detected at index 1.
    """
    threshold = 2.0
    z = [threshold + 0.1] * 10
    result = cusum_detector(z, threshold=threshold, drift=0.0)
    assert len(result["signals"]) > 0
    assert result["signals"][0] == 1, (
        f"Expected first signal at index 1, got {result['signals'][0]}"
    )


# ─── Platt calibration tests ──────────────────────────────────────────────────


def test_platt_too_few_samples_returns_defaults():
    """len < 10 → center=0, scale=1, log_loss=inf."""
    scores = np.array([0.1, 0.5, 0.9])
    outcomes = np.array([0, 1, 1])
    result = platt_calibration(scores, outcomes)
    assert result["center"] == 0.0
    assert result["scale"] == 1.0
    assert result["log_loss"] == float("inf")


def test_platt_returns_center_scale_log_loss():
    """platt_calibration returns dict with three float keys."""
    rng = np.random.default_rng(42)
    scores = rng.uniform(0, 1, 50)
    outcomes = (scores > 0.5).astype(float)
    result = platt_calibration(scores, outcomes)
    assert set(result.keys()) == {"center", "scale", "log_loss"}
    assert isinstance(result["center"], float)
    assert isinstance(result["scale"], float)
    assert isinstance(result["log_loss"], float)


def test_platt_separable_data():
    """Perfect separation → log_loss should be smaller than for random."""
    rng = np.random.default_rng(0)
    scores_sep = np.concatenate([rng.uniform(0.0, 0.4, 50), rng.uniform(0.6, 1.0, 50)])
    outcomes_sep = np.concatenate([np.zeros(50), np.ones(50)])
    result_sep = platt_calibration(scores_sep, outcomes_sep)

    scores_rand = rng.uniform(0, 1, 100)
    outcomes_rand = rng.integers(0, 2, 100).astype(float)
    result_rand = platt_calibration(scores_rand, outcomes_rand)

    assert result_sep["log_loss"] < result_rand["log_loss"]


def test_platt_log_loss_positive():
    """log_loss must be >= 0."""
    rng = np.random.default_rng(42)
    scores = rng.uniform(0, 1, 30)
    outcomes = rng.integers(0, 2, 30).astype(float)
    result = platt_calibration(scores, outcomes)
    assert result["log_loss"] >= 0.0
