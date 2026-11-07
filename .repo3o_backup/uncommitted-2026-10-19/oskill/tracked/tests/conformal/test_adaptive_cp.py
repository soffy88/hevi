"""Tests for oskill.conformal.adaptive_cp.adaptive_conformal_inference."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.conformal.adaptive_cp import adaptive_conformal_inference


def _make_data(n=200, noise_std=1.0, seed=42):
    rng = np.random.default_rng(seed)
    preds = rng.normal(0, 1, n)
    acts = preds + rng.normal(0, noise_std, n)
    return preds, acts


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts)
    expected = {
        "lower",
        "upper",
        "alphas",
        "empirical_coverage_running",
        "final_alpha",
        "long_run_coverage",
        "adaptation_rate",
    }
    assert expected == set(result.keys())


def test_output_shapes():
    n = 150
    preds, acts = _make_data(n=n)
    result = adaptive_conformal_inference(preds, acts)
    assert result["lower"].shape == (n,)
    assert result["upper"].shape == (n,)
    assert result["alphas"].shape == (n,)
    assert result["empirical_coverage_running"].shape == (n,)


def test_lower_leq_upper():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts)
    assert np.all(result["lower"] <= result["upper"])


def test_alphas_bounded():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts)
    assert np.all(result["alphas"] >= 0.001)
    assert np.all(result["alphas"] <= 0.999)


def test_long_run_coverage_near_target():
    """Long-run coverage should be near (1-alpha_target) on stationary data."""
    rng = np.random.default_rng(0)
    n = 500
    preds = rng.normal(0, 1, n)
    acts = preds + rng.normal(0, 1, n)
    alpha_target = 0.10
    result = adaptive_conformal_inference(preds, acts, alpha_target=alpha_target)
    # Allow generous tolerance on long-run coverage
    assert result["long_run_coverage"] >= 0.70, (
        f"Long-run coverage {result['long_run_coverage']:.3f} too low"
    )


def test_adaptation_rate_returned():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts, gamma=0.01)
    assert abs(result["adaptation_rate"] - 0.01) < 1e-10


def test_mismatched_lengths_raise():
    preds = np.zeros(100)
    acts = np.zeros(90)
    with pytest.raises(ValueError, match="same length"):
        adaptive_conformal_inference(preds, acts)


def test_invalid_alpha_target_raises():
    preds, acts = _make_data()
    with pytest.raises(ValueError, match="alpha_target"):
        adaptive_conformal_inference(preds, acts, alpha_target=0.0)
    with pytest.raises(ValueError, match="alpha_target"):
        adaptive_conformal_inference(preds, acts, alpha_target=1.5)


def test_initial_alpha_accepted():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts, initial_alpha=0.15)
    assert isinstance(result["final_alpha"], float)


def test_signed_score_function():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts, score_function="signed")
    assert result["lower"].shape == preds.shape
    assert np.all(result["lower"] <= result["upper"])


def test_empirical_coverage_running_bounds():
    preds, acts = _make_data()
    result = adaptive_conformal_inference(preds, acts)
    ecr = result["empirical_coverage_running"]
    assert np.all(ecr >= 0.0) and np.all(ecr <= 1.0)
