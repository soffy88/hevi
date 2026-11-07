"""Tests for gaussian_process_regression."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oskill.bayesian.gp_regression import gaussian_process_regression

EXPECTED_KEYS = {
    "posterior_mean",
    "posterior_std",
    "posterior_covariance",
    "log_marginal_likelihood",
    "optimized_kernel_params",
    "optimized_noise_variance",
}


def _make_sin_data(rng, n_train=20, noise=0.1):
    X_train = rng.uniform(0, 2 * np.pi, size=(n_train, 1))
    y_train = np.sin(X_train[:, 0]) + noise * rng.standard_normal(n_train)
    X_test = np.linspace(0, 2 * np.pi, 30).reshape(-1, 1)
    return X_train, y_train, X_test


def test_gpr_rbf_basic():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_te, kernel="rbf", optimize_hyperparameters=False, seed=42
    )
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_mean"].shape == (30,)
    assert result["posterior_std"].shape == (30,)


def test_gpr_matern_basic():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_te, kernel="matern", optimize_hyperparameters=False, seed=42
    )
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_mean"].shape == (30,)


def test_gpr_periodic_basic():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_te, kernel="periodic", optimize_hyperparameters=False, seed=42
    )
    assert EXPECTED_KEYS.issubset(result.keys())


def test_gpr_rational_quadratic_basic():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_te, kernel="rational_quadratic", optimize_hyperparameters=False, seed=42
    )
    assert EXPECTED_KEYS.issubset(result.keys())


def test_gpr_posterior_mean_close_to_truth():
    np.random.default_rng(42)
    # Very low noise so GP should interpolate well
    X_tr = np.linspace(0, 2 * np.pi, 15).reshape(-1, 1)
    y_tr = np.sin(X_tr[:, 0])
    X_te = np.linspace(0.3, 5.9, 20).reshape(-1, 1)
    y_true = np.sin(X_te[:, 0])
    result = gaussian_process_regression(
        X_tr,
        y_tr,
        X_te,
        kernel="rbf",
        noise_variance=1e-4,
        optimize_hyperparameters=False,
        kernel_params={"sigma_f": 1.0, "length_scale": 1.0},
    )
    # Mean absolute error should be small
    mae = float(np.mean(np.abs(result["posterior_mean"] - y_true)))
    assert mae < 0.3, f"GPR MAE = {mae:.4f}"


def test_gpr_posterior_std_positive():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_te, kernel="rbf", optimize_hyperparameters=False
    )
    assert np.all(result["posterior_std"] >= 0.0)
    # At least some uncertainty should exist
    assert np.any(result["posterior_std"] > 1e-10)


def test_gpr_optimize_hyperparameters_runs():
    rng = np.random.default_rng(42)
    X_tr, y_tr, X_te = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr,
        y_tr,
        X_te,
        kernel="rbf",
        optimize_hyperparameters=True,
        n_restarts=2,
        seed=42,
    )
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["optimized_noise_variance"] > 0.0


def test_gpr_no_test_data_predicts_on_train():
    rng = np.random.default_rng(42)
    X_tr, y_tr, _ = _make_sin_data(rng)
    result = gaussian_process_regression(
        X_tr, y_tr, X_test=None, kernel="rbf", optimize_hyperparameters=False
    )
    assert result["posterior_mean"].shape == (len(X_tr),)


def test_gpr_log_marginal_likelihood_is_float():
    rng = np.random.default_rng(42)
    X_tr, y_tr, _ = _make_sin_data(rng)
    result = gaussian_process_regression(X_tr, y_tr, kernel="rbf", optimize_hyperparameters=False)
    assert isinstance(result["log_marginal_likelihood"], float)
    assert np.isfinite(result["log_marginal_likelihood"])


def test_gpr_dataframe_input():
    rng = np.random.default_rng(42)
    X_tr_arr, y_tr_arr, X_te_arr = _make_sin_data(rng)
    X_tr_df = pd.DataFrame(X_tr_arr, columns=["x"])
    y_tr_ser = pd.Series(y_tr_arr)
    X_te_df = pd.DataFrame(X_te_arr, columns=["x"])
    result = gaussian_process_regression(
        X_tr_df, y_tr_ser, X_te_df, kernel="rbf", optimize_hyperparameters=False
    )
    assert EXPECTED_KEYS.issubset(result.keys())
    assert result["posterior_mean"].shape == (30,)
