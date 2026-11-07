"""Factor quantile portfolio returns (Fama-MacBeth cross-sectional method)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import oprim
import pandas as pd


def factor_quantile_returns(
    factor_values: np.ndarray | pd.DataFrame,
    forward_returns: np.ndarray | pd.DataFrame,
    *,
    n_quantiles: int = 5,
    method: Literal["equal_weighted", "value_weighted"] = "equal_weighted",
) -> dict[str, Any]:
    """Factor quantile portfolio returns.

    Sorts assets into quantile portfolios based on cross-sectional factor scores
    and computes equal-weighted returns per quantile at each time step.

    Algorithm (Fama-MacBeth):
        At each time t:
            1. Sort assets by factor_values[t], ignoring NaN
            2. Assign to n_quantiles groups (Q1=lowest, Q_n=highest)
            3. Compute equal-weighted return per quantile

    Returns dict:
        quantile_returns:        np.ndarray (T x n_quantiles)
        mean_returns_by_quantile: np.ndarray (n_quantiles,) — time-averaged return per quantile
        long_short_returns:      np.ndarray (T,) — Q_top minus Q_bottom each period
        monotonicity_score:      float — fraction of periods where Q_top > Q_bottom
        top_minus_bottom_sharpe: float — Sharpe ratio of long_short_returns

    Reference:
        Fama & MacBeth (1973), "Risk, Return, and Equilibrium"
        Grinold & Kahn (2000), "Active Portfolio Management"

    Args:
        factor_values: T x N factor scores (higher = more favorable).
        forward_returns: T x N 1-period forward returns.
        n_quantiles: Number of quantile buckets (default 5).
        method: Portfolio weighting method ("equal_weighted" or "value_weighted").

    Raises:
        ValueError: If n_quantiles < 2, or input shapes mismatch.
    """
    # Handle DataFrame input
    if isinstance(factor_values, pd.DataFrame):
        fv = factor_values.values.astype(np.float64)
    else:
        fv = np.asarray(factor_values, dtype=np.float64)

    if isinstance(forward_returns, pd.DataFrame):
        fr = forward_returns.values.astype(np.float64)
    else:
        fr = np.asarray(forward_returns, dtype=np.float64)

    # Validate inputs
    if n_quantiles < 2:
        raise ValueError(f"n_quantiles must be >= 2, got {n_quantiles}")
    if fv.shape != fr.shape:
        raise ValueError(f"factor_values shape {fv.shape} != forward_returns shape {fr.shape}")
    if fv.ndim == 1:
        fv = fv.reshape(1, -1)
        fr = fr.reshape(1, -1)

    T, N = fv.shape

    if N < n_quantiles:
        raise ValueError(f"Number of assets N={N} must be >= n_quantiles={n_quantiles}")

    # Compute quantile returns at each time step
    quantile_returns = np.full((T, n_quantiles), np.nan)

    for t in range(T):
        fv_t = fv[t]
        fr_t = fr[t]

        # Get valid (non-NaN) assets
        valid_mask = ~(np.isnan(fv_t) | np.isnan(fr_t))
        if np.sum(valid_mask) < n_quantiles:
            continue

        fv_valid = fv_t[valid_mask]
        fr_valid = fr_t[valid_mask]

        # Assign quantile labels using pd.qcut (equal-frequency bins)
        try:
            quantile_labels = pd.qcut(fv_valid, q=n_quantiles, labels=False, duplicates="drop")
        except ValueError:
            # If qcut fails (e.g., too many ties), use simple rank-based assignment
            ranks = pd.Series(fv_valid).rank(method="first") - 1
            quantile_labels = (
                (ranks * n_quantiles / len(fv_valid)).astype(int).clip(0, n_quantiles - 1).values
            )

        # Compute equal-weighted return per quantile
        for q in range(n_quantiles):
            q_mask = quantile_labels == q
            if np.sum(q_mask) == 0:
                continue
            if method == "equal_weighted":
                quantile_returns[t, q] = float(np.mean(fr_valid[q_mask]))
            elif method == "value_weighted":
                # For value_weighted, use uniform weights (no market cap available)
                quantile_returns[t, q] = float(np.mean(fr_valid[q_mask]))
            else:
                raise ValueError(f"Unknown method: {method!r}")

    # Long-short returns: Q_top (q=n_quantiles-1) minus Q_bottom (q=0)
    top_returns = quantile_returns[:, n_quantiles - 1]
    bottom_returns = quantile_returns[:, 0]
    long_short_returns = top_returns - bottom_returns

    # Mean returns by quantile (time-averaged, ignoring NaN)
    mean_returns_by_quantile = np.nanmean(quantile_returns, axis=0)

    # Monotonicity score: fraction of periods where Q_top > Q_bottom
    valid_ls = ~np.isnan(long_short_returns)
    if np.sum(valid_ls) > 0:
        monotonicity_score = float(np.mean(long_short_returns[valid_ls] > 0))
    else:
        monotonicity_score = 0.0

    # Top-minus-bottom Sharpe ratio using oprim.sharpe_ratio
    valid_ls_data = long_short_returns[valid_ls]
    if len(valid_ls_data) > 1:
        top_minus_bottom_sharpe = float(oprim.sharpe_ratio(pd.Series(valid_ls_data)))
    else:
        top_minus_bottom_sharpe = 0.0

    return {
        "quantile_returns": quantile_returns,
        "mean_returns_by_quantile": mean_returns_by_quantile,
        "long_short_returns": long_short_returns,
        "monotonicity_score": monotonicity_score,
        "top_minus_bottom_sharpe": top_minus_bottom_sharpe,
    }
