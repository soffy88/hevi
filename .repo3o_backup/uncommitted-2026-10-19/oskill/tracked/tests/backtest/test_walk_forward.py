"""Tests for walk_forward_optimization_pipeline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.backtest.walk_forward_optimization import walk_forward_optimization_pipeline


def _simple_optimization(X_train, y_train):
    return {"mean_param": float(np.mean(X_train.iloc[:, 0]))}


def _simple_strategy(X_test, params):
    rng = np.random.default_rng(42)
    return pd.Series(rng.normal(0, 0.01, len(X_test)), index=X_test.index)


@pytest.fixture
def wfo_data():
    rng = np.random.default_rng(42)
    T = 500
    X = pd.DataFrame(rng.standard_normal((T, 3)))
    y = pd.Series(rng.standard_normal(T))
    return X, y


def test_wfo_basic(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    expected_keys = {
        "walk_forward_returns",
        "parameter_history",
        "param_stability",
        "oos_sharpe",
        "in_sample_vs_oos_degradation",
        "n_walks",
    }
    assert set(result.keys()) == expected_keys


def test_wfo_walk_forward_returns_is_series(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    assert isinstance(result["walk_forward_returns"], pd.Series)
    assert len(result["walk_forward_returns"]) > 0


def test_wfo_parameter_history_shape(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    assert isinstance(result["parameter_history"], pd.DataFrame)
    assert result["parameter_history"].shape[0] == result["n_walks"]


def test_wfo_n_walks_positive(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    assert result["n_walks"] > 0


def test_wfo_oos_sharpe_is_float(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    assert isinstance(result["oos_sharpe"], float)
    assert np.isfinite(result["oos_sharpe"])


def test_wfo_param_stability_keys(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    for param_name, stability in result["param_stability"].items():
        assert set(stability.keys()) == {"mean", "std", "drift"}
        assert np.isfinite(stability["mean"])
        assert np.isfinite(stability["std"])
        assert np.isfinite(stability["drift"])


def test_wfo_custom_step_size(wfo_data):
    X, y = wfo_data
    result_default = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
    )
    result_step = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
        step_size=25,
    )
    # Smaller step_size → more walks
    assert result_step["n_walks"] >= result_default["n_walks"]


def test_wfo_n_iterations_limit(wfo_data):
    X, y = wfo_data
    result = walk_forward_optimization_pipeline(
        X,
        y,
        _simple_strategy,
        optimization_function=_simple_optimization,
        train_window=200,
        test_window=50,
        n_iterations=2,
    )
    assert result["n_walks"] == 2
