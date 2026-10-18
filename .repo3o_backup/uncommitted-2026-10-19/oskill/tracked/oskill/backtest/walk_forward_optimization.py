"""Walk-Forward Optimization Pipeline (Pardo 2008)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd


def walk_forward_optimization_pipeline(
    X: pd.DataFrame,
    y: pd.Series | np.ndarray,
    strategy_fn: Callable[[pd.DataFrame, dict[str, Any]], pd.Series],
    *,
    optimization_function: Callable[[pd.DataFrame, Any], dict[str, Any]],
    train_window: int = 252,
    test_window: int = 63,
    step_size: int | None = None,
    n_iterations: int | None = None,
) -> dict[str, Any]:
    """Walk-Forward Optimization Pipeline.

    Repeatedly trains on a rolling in-sample window, optimizes parameters,
    then applies the strategy to the subsequent out-of-sample window.
    Aggregates OOS returns and tracks parameter evolution over walks.

    Algorithm:
        step = test_window if step_size is None
        t = 0
        While T - t - train_window >= test_window:
            params = optimization_function(X[t:t+train_window], y[t:t+train_window])
            oos_returns = strategy_fn(X[t+train_window:t+train_window+test_window], params)
            t += step

    Param stability measured as (mean, std, drift) where drift is the OLS
    slope of parameter values over walk index.

    OOS Sharpe = mean(oos_returns) / std(oos_returns) * sqrt(252).
    in_sample_vs_oos_degradation = 0 when IS Sharpe cannot be computed.

    Args:
        X: Feature DataFrame of shape (T, P) with DatetimeIndex or RangeIndex.
        y: Target vector of shape (T,).
        strategy_fn: Callable(X_test, params) → pd.Series of returns.
        optimization_function: Callable(X_train, y_train) → dict of optimal params.
        train_window: Number of observations for in-sample training.
        test_window: Number of observations for out-of-sample testing.
        step_size: Observations to advance after each walk (default: test_window).
        n_iterations: Maximum number of walks to run (None = unlimited).

    Returns:
        walk_forward_returns: pd.Series concatenated OOS returns
        parameter_history: pd.DataFrame one row per walk
        param_stability: dict {param: {"mean", "std", "drift"}}
        oos_sharpe: float
        in_sample_vs_oos_degradation: float
        n_walks: int

    Reference:
        Pardo (2008).
    """
    if isinstance(X, np.ndarray):
        X = pd.DataFrame(X)
    if isinstance(y, np.ndarray):
        y = pd.Series(y)

    T = len(X)
    if step_size is None:
        step_size = test_window

    all_returns: list[pd.Series] = []
    param_rows: list[dict[str, Any]] = []
    walk_count = 0

    t = 0
    while T - t - train_window >= test_window:
        if n_iterations is not None and walk_count >= n_iterations:
            break

        X_train = X.iloc[t : t + train_window]
        y_train = y.iloc[t : t + train_window]
        X_test = X.iloc[t + train_window : t + train_window + test_window]

        params = optimization_function(X_train, y_train)
        oos_ret = strategy_fn(X_test, params)

        all_returns.append(oos_ret)
        param_rows.append(params)
        walk_count += 1
        t += step_size

    if not all_returns:
        empty_ret = pd.Series(dtype=float)
        return {
            "walk_forward_returns": empty_ret,
            "parameter_history": pd.DataFrame(),
            "param_stability": {},
            "oos_sharpe": 0.0,
            "in_sample_vs_oos_degradation": 0.0,
            "n_walks": 0,
        }

    wf_returns = pd.concat(all_returns)
    param_df = pd.DataFrame(param_rows)

    ret_vals = wf_returns.values
    if len(ret_vals) > 1:
        mu = float(np.mean(ret_vals))
        sig = float(np.std(ret_vals, ddof=1))
        oos_sharpe = mu / sig * np.sqrt(252) if sig > 1e-12 else 0.0
    else:
        oos_sharpe = 0.0

    param_stability: dict[str, dict[str, float]] = {}
    n = len(param_df)
    walk_index = np.arange(n, dtype=float)
    for col in param_df.columns:
        vals = param_df[col].values.astype(float)
        mean_v = float(np.mean(vals))
        std_v = float(np.std(vals, ddof=1)) if n > 1 else 0.0
        # OLS slope as drift
        if n > 1:
            x_c = walk_index - walk_index.mean()
            drift = float(np.sum(x_c * (vals - mean_v)) / np.sum(x_c**2))
        else:
            drift = 0.0
        param_stability[str(col)] = {"mean": mean_v, "std": std_v, "drift": drift}

    return {
        "walk_forward_returns": wf_returns,
        "parameter_history": param_df,
        "param_stability": param_stability,
        "oos_sharpe": float(oos_sharpe),
        "in_sample_vs_oos_degradation": 0.0,
        "n_walks": walk_count,
    }
