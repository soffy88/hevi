"""Tests for bayesian_linear_regression."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oskill.bayesian.linear_regression import bayesian_linear_regression

EXPECTED_KEYS = {
    "posterior_mean",
    "posterior_covariance",
    "posterior_samples",
    "noise_variance_mean",
    "noise_variance_samples",
    "credible_intervals",
    "effective_sample_size",
    "log_marginal_likelihood",
}


def _make_linear_data(rng, n=100, true_intercept=2.0, true_slope=3.0, noise=0.5):
    X = rng.standard_normal((n, 1))
    y = true_intercept + true_slope * X[:, 0] + noise * rng.standard_normal(n)
    return X, y


def test_blr_conjugate_basic():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng)
    result = bayesian_linear_regression(X, y, method="conjugate")
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_mean"].shape == (2,)  # intercept + slope
    assert result["posterior_covariance"].shape == (2, 2)
    assert isinstance(result["log_marginal_likelihood"], float)


def test_blr_conjugate_posterior_mean_close_to_ols():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng, n=200)
    # Weak prior: small precision => posterior ~ OLS
    result = bayesian_linear_regression(X, y, prior_precision=1e-6 * np.eye(2), method="conjugate")
    n = len(y)
    ones = np.ones(n)
    X_full = np.column_stack([ones, X[:, 0]])
    ols_beta = np.linalg.lstsq(X_full, y, rcond=None)[0]
    np.testing.assert_allclose(result["posterior_mean"], ols_beta, rtol=0.05)


def test_blr_conjugate_credible_intervals_contain_true():
    rng = np.random.default_rng(42)
    true_intercept = 2.0
    true_slope = 3.0
    X, y = _make_linear_data(rng, n=150, true_intercept=true_intercept, true_slope=true_slope)
    result = bayesian_linear_regression(X, y, method="conjugate")
    ci = result["credible_intervals"]["95%"]
    # Check true intercept and slope are inside 95% CI
    assert ci["lower"][0] < true_intercept < ci["upper"][0]
    assert ci["lower"][1] < true_slope < ci["upper"][1]


def test_blr_conjugate_prior_dominates_with_strong_prior():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng, n=50, true_intercept=5.0, true_slope=5.0)
    prior_mean = np.array([0.0, 0.0])
    # Very strong prior: precision = 1e6 * I => posterior pulled hard toward 0
    result = bayesian_linear_regression(
        X,
        y,
        prior_mean=prior_mean,
        prior_precision=1e6 * np.eye(2),
        method="conjugate",
    )
    # Posterior mean should be closer to prior_mean (0) than to true values (5)
    assert np.abs(result["posterior_mean"][1]) < 3.0


def test_blr_mcmc_basic():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng, n=80)
    result = bayesian_linear_regression(X, y, method="mcmc", n_mcmc_samples=500, seed=42)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_samples"] is not None
    assert result["noise_variance_samples"] is not None


def test_blr_mcmc_posterior_samples_shape():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng, n=80)
    n_samples = 300
    result = bayesian_linear_regression(X, y, method="mcmc", n_mcmc_samples=n_samples, seed=7)
    # p = 2 (intercept + 1 feature)
    assert result["posterior_samples"].shape == (n_samples, 2)


def test_blr_noise_variance_positive():
    rng = np.random.default_rng(42)
    X, y = _make_linear_data(rng)
    for method in ("conjugate", "mcmc"):
        result = bayesian_linear_regression(X, y, method=method, n_mcmc_samples=200, seed=0)
        assert result["noise_variance_mean"] > 0.0


def test_blr_dataframe_input():
    rng = np.random.default_rng(42)
    X_arr, y_arr = _make_linear_data(rng, n=80)
    X_df = pd.DataFrame(X_arr, columns=["x1"])
    y_ser = pd.Series(y_arr)
    result = bayesian_linear_regression(X_df, y_ser, method="conjugate")
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_mean"].shape[0] == 2
