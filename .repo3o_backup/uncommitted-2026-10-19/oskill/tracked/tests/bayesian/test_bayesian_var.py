"""Tests for bayesian_var."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oskill.bayesian.var import bayesian_var

EXPECTED_KEYS = {
    "posterior_coefficients_mean",
    "posterior_coefficients_samples",
    "posterior_sigma_mean",
    "posterior_sigma_samples",
    "impulse_responses",
    "forecast_error_variance_decomp",
    "log_marginal_likelihood",
}


def _make_var_data(rng, T=120, K=2, p=1):
    """Generate stationary VAR(p) data."""
    # Simple stationary VAR
    A = np.array([[0.5, 0.1], [0.05, 0.4]]) if K == 2 else np.eye(K) * 0.4
    data = np.zeros((T, K))
    data[:p] = rng.standard_normal((p, K))
    for t in range(p, T):
        for l in range(1, p + 1):
            data[t] += data[t - l] @ A.T
        data[t] += rng.standard_normal(K) * 0.3
    return data


def test_bvar_basic_bivariate():
    rng = np.random.default_rng(42)
    data = _make_var_data(rng, T=100)
    result = bayesian_var(data, p_lag=1, prior="minnesota")
    assert EXPECTED_KEYS.issubset(result.keys())


def test_bvar_coefficient_shape():
    rng = np.random.default_rng(42)
    K, p = 2, 1
    data = _make_var_data(rng, T=100, K=K, p=p)
    result = bayesian_var(data, p_lag=p)
    assert result["posterior_coefficients_mean"].shape == (K, K * p + 1)


def test_bvar_impulse_responses_shape():
    rng = np.random.default_rng(42)
    K, p = 2, 1
    data = _make_var_data(rng, T=100, K=K, p=p)
    result = bayesian_var(data, p_lag=p)
    assert result["impulse_responses"].shape == (K, K, 10)


def test_bvar_normal_wishart_prior():
    rng = np.random.default_rng(42)
    data = _make_var_data(rng, T=120)
    result = bayesian_var(data, p_lag=1, prior="normal_wishart")
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_coefficients_mean"].shape[0] == 2


def test_bvar_uninformative_close_to_ols():
    rng = np.random.default_rng(42)
    K, p = 2, 1
    data = _make_var_data(rng, T=200, K=K, p=p)
    result_uninf = bayesian_var(data, p_lag=p, prior="uninformative")
    # Compare with OLS manually
    T, K_actual = data.shape
    T_eff = T - p
    Z = np.ones((T_eff, K_actual * p + 1))
    Z[:, 1:] = data[p - 1 : T - 1]
    Y_eff = data[p:]
    ZTZ = Z.T @ Z
    ZTY = Z.T @ Y_eff
    A_ols = np.linalg.solve(ZTZ + 1e-10 * np.eye(K_actual * p + 1), ZTY).T
    np.testing.assert_allclose(result_uninf["posterior_coefficients_mean"], A_ols, rtol=1e-4)


def test_bvar_fevd_sums_to_one():
    rng = np.random.default_rng(42)
    data = _make_var_data(rng, T=120)
    result = bayesian_var(data, p_lag=1)
    FEVD = result["forecast_error_variance_decomp"]
    K = FEVD.shape[0]
    for h in range(10):
        for resp in range(K):
            total = FEVD[resp, :, h].sum()
            assert abs(total - 1.0) < 1e-6, f"FEVD at h={h}, resp={resp} sums to {total}"


def test_bvar_log_ml_is_float():
    rng = np.random.default_rng(42)
    data = _make_var_data(rng, T=100)
    result = bayesian_var(data)
    assert isinstance(result["log_marginal_likelihood"], float)
    assert np.isfinite(result["log_marginal_likelihood"])


def test_bvar_dataframe_input():
    rng = np.random.default_rng(42)
    data = _make_var_data(rng, T=100)
    df = pd.DataFrame(data, columns=["y1", "y2"])
    result = bayesian_var(df, p_lag=1)
    assert EXPECTED_KEYS.issubset(result.keys())


def test_bvar_trivariate():
    rng = np.random.default_rng(42)
    K = 3
    data = _make_var_data(rng, T=150, K=K, p=1)
    result = bayesian_var(data, p_lag=1)
    assert result["posterior_coefficients_mean"].shape == (K, K * 1 + 1)
    assert result["impulse_responses"].shape == (K, K, 10)
    assert result["forecast_error_variance_decomp"].shape == (K, K, 10)
