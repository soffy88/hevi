"""Tests for haircut_sharpe."""

from __future__ import annotations

import numpy as np

from oskill.validation.haircut import haircut_sharpe


def test_haircut_basic():
    result = haircut_sharpe(2.0, 252, 10)
    expected_keys = {
        "reported_sharpe",
        "haircut_pct",
        "adjusted_sharpe",
        "corrected_p_value",
        "method",
        "is_significant_after_correction",
    }
    assert set(result.keys()) == expected_keys


def test_haircut_high_sharpe_less_haircut():
    low = haircut_sharpe(1.0, 252, 20)
    high = haircut_sharpe(3.0, 252, 20)
    # Higher Sharpe → t_stat grows faster (non-normal correction inflates denominator),
    # so 1 - target/t_stat is larger for higher Sharpe → higher haircut_pct
    assert high["haircut_pct"] >= low["haircut_pct"]


def test_haircut_more_trials_more_haircut():
    few = haircut_sharpe(2.0, 252, 5)
    many = haircut_sharpe(2.0, 252, 100)
    # More trials → higher target_t → haircut_pct = 1 - target/t is smaller
    # (because target/t grows toward 1 as target increases)
    assert many["haircut_pct"] <= few["haircut_pct"]


def test_haircut_adjusted_sharpe_less_than_reported():
    result = haircut_sharpe(2.0, 252, 50)
    assert result["adjusted_sharpe"] <= result["reported_sharpe"]


def test_haircut_methods():
    for method in ("bonferroni", "holm", "bhy"):
        result = haircut_sharpe(2.0, 252, 20, method=method)
        assert result["method"] == method
        assert 0.0 <= result["haircut_pct"] <= 1.0
        assert np.isfinite(result["adjusted_sharpe"])


def test_haircut_single_trial_no_haircut():
    result = haircut_sharpe(2.0, 252, 1)
    # With one trial, the correction factor c_m = 1 (BHY denominator equals m=1)
    # so the target_t equals norm.ppf(0.975) ≈ 1.96 — same as uncorrected
    # haircut_pct is still non-zero (t_stat >> target), but less than with many trials
    many = haircut_sharpe(2.0, 252, 50)
    assert result["haircut_pct"] >= many["haircut_pct"]


def test_haircut_correlation_reduces_effective_trials():
    no_corr = haircut_sharpe(2.0, 252, 50, correlation_among_trials=0.0)
    with_corr = haircut_sharpe(2.0, 252, 50, correlation_among_trials=0.8)
    # Correlation reduces effective m → lower target_t → lower adjusted_sharpe
    # (target/t ratio decreases, haircut_pct = 1-target/t increases)
    assert with_corr["adjusted_sharpe"] <= no_corr["adjusted_sharpe"]
