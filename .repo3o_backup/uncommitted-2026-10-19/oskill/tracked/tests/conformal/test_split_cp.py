"""Tests for oskill.conformal.split_cp.conformal_prediction_interval."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.conformal.split_cp import conformal_prediction_interval

# ─── helpers ──────────────────────────────────────────────────────────────────


def _make_synthetic(n_cal=200, n_test=100, noise_std=1.0, seed=42):
    rng = np.random.default_rng(seed)
    cal_preds = rng.normal(0, 1, n_cal)
    cal_acts = cal_preds + rng.normal(0, noise_std, n_cal)
    test_preds = rng.normal(0, 1, n_test)
    test_acts = test_preds + rng.normal(0, noise_std, n_test)
    return cal_preds, cal_acts, test_preds, test_acts


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    result = conformal_prediction_interval(cal_p, cal_a, test_p)
    expected = {
        "lower",
        "upper",
        "point_predictions",
        "quantile_used",
        "alpha",
        "expected_coverage",
        "fingerprint",
    }
    assert expected == set(result.keys())


def test_lower_upper_shapes():
    cal_p, cal_a, test_p, _ = _make_synthetic(n_test=50)
    result = conformal_prediction_interval(cal_p, cal_a, test_p)
    assert result["lower"].shape == (50,)
    assert result["upper"].shape == (50,)


def test_lower_leq_upper():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    result = conformal_prediction_interval(cal_p, cal_a, test_p)
    assert np.all(result["lower"] <= result["upper"])


def test_expected_coverage_value():
    result = conformal_prediction_interval(np.zeros(100), np.zeros(100), np.zeros(10), alpha=0.1)
    assert abs(result["expected_coverage"] - 0.9) < 1e-9
    assert abs(result["alpha"] - 0.1) < 1e-9


def test_quantile_used_non_negative_absolute():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    result = conformal_prediction_interval(cal_p, cal_a, test_p, score_function="absolute")
    assert result["quantile_used"] >= 0.0


def test_marginal_coverage_at_least_1_minus_alpha():
    """Empirical coverage on test set should be >= 1 - alpha."""
    rng = np.random.default_rng(0)
    n_cal, n_test = 500, 300
    true_std = 1.5
    cal_p = rng.normal(0, 1, n_cal)
    cal_a = cal_p + rng.normal(0, true_std, n_cal)
    test_p = rng.normal(0, 1, n_test)
    test_a = test_p + rng.normal(0, true_std, n_test)

    alpha = 0.10
    result = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=alpha)
    covered = np.mean((test_a >= result["lower"]) & (test_a <= result["upper"]))
    assert covered >= 1 - alpha - 0.05, f"Coverage {covered:.3f} < {1 - alpha - 0.05:.3f}"


def test_fingerprint_is_hex64():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    result = conformal_prediction_interval(cal_p, cal_a, test_p)
    fp = result["fingerprint"]
    assert isinstance(fp, str) and len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_fingerprint_deterministic():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    r1 = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.05)
    r2 = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.05)
    assert r1["fingerprint"] == r2["fingerprint"]


def test_fingerprint_changes_with_alpha():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    r1 = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.05)
    r2 = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.20)
    assert r1["fingerprint"] != r2["fingerprint"]


def test_larger_alpha_gives_smaller_intervals():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    r_tight = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.01)
    r_wide = conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.30)
    # Larger alpha → more miscoverage → smaller intervals
    assert r_wide["quantile_used"] <= r_tight["quantile_used"]


def test_invalid_alpha_raises():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    with pytest.raises(ValueError, match="alpha"):
        conformal_prediction_interval(cal_p, cal_a, test_p, alpha=0.0)
    with pytest.raises(ValueError, match="alpha"):
        conformal_prediction_interval(cal_p, cal_a, test_p, alpha=1.0)
    with pytest.raises(ValueError, match="alpha"):
        conformal_prediction_interval(cal_p, cal_a, test_p, alpha=-0.1)


def test_invalid_score_function_raises():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    with pytest.raises(ValueError, match="score_function"):
        conformal_prediction_interval(cal_p, cal_a, test_p, score_function="unknown")


def test_normalized_score_function():
    rng = np.random.default_rng(7)
    n_cal, n_test = 200, 50
    cal_p = rng.normal(0, 1, n_cal)
    cal_a = cal_p + rng.normal(0, 1, n_cal)
    test_p = rng.normal(0, 1, n_test)
    sigma = np.abs(rng.normal(1, 0.1, n_cal))
    result = conformal_prediction_interval(
        cal_p,
        cal_a,
        test_p,
        score_function="normalized",
        score_normalizer=sigma,
    )
    assert result["lower"].shape == (n_test,)
    assert np.all(result["lower"] <= result["upper"])


def test_normalized_missing_normalizer_raises():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    with pytest.raises(ValueError, match="score_normalizer"):
        conformal_prediction_interval(cal_p, cal_a, test_p, score_function="normalized")


def test_signed_score_function():
    cal_p, cal_a, test_p, _ = _make_synthetic()
    result = conformal_prediction_interval(cal_p, cal_a, test_p, score_function="signed")
    assert result["lower"].shape == test_p.shape
    assert np.all(result["lower"] <= result["upper"])


def test_accepts_pandas_series():
    import pandas as pd

    rng = np.random.default_rng(1)
    cal_p = pd.Series(rng.normal(0, 1, 100))
    cal_a = pd.Series(rng.normal(0, 1, 100))
    test_p = pd.Series(rng.normal(0, 1, 30))
    result = conformal_prediction_interval(cal_p, cal_a, test_p)
    assert result["lower"].shape == (30,)
