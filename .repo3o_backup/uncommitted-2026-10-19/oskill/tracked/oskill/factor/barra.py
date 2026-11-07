"""Barra-style multi-factor risk model (cross-sectional regression)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def barra_style_decomposition(
    asset_returns: pd.DataFrame,
    style_factors: pd.DataFrame,
    *,
    factor_names: list[str] | None = None,
    cross_sectional_regression: bool = True,
) -> dict[str, Any]:
    """Barra-style multi-factor risk model.

    Decomposes asset returns into systematic factor returns and asset-specific
    (idiosyncratic) returns via cross-sectional OLS regression at each period.

    Cross-sectional regression at each timestamp t:
        r_i,t = sum_k (style_score_i,k,t * factor_return_k,t) + specific_i,t

    In the simplified implementation (style_factors: T x K):
        - At each t, OLS regress N asset returns on K factor exposures
        - factor_returns[t] = estimated factor returns (K-vector)
        - specific_returns[t] = residuals from each OLS (N-vector)

    This is equivalent to assuming all assets share the same style exposure
    matrix at each time period (factor exposures vary over time but not
    cross-sectionally).

    Args:
        asset_returns: T x N DataFrame (T timestamps, N assets).
        style_factors: T x K DataFrame of factor exposures at each period.
        factor_names: Names for factors (default: style_factors column names).
        cross_sectional_regression: If True (default), OLS at each t.

    Returns dict:
        - 'factor_returns': pd.DataFrame (T x K) estimated factor returns per period
        - 'specific_returns': pd.DataFrame (T x N) residuals per asset per period
        - 'r_squared_per_period': array (T,) R^2 at each time t
        - 'mean_r_squared': float average R^2

    Raises:
        ValueError: If shapes are incompatible.
    """
    if not isinstance(asset_returns, pd.DataFrame):
        raise ValueError("asset_returns must be a pd.DataFrame")
    if not isinstance(style_factors, pd.DataFrame):
        raise ValueError("style_factors must be a pd.DataFrame")

    T, N = asset_returns.shape
    T2, K = style_factors.shape

    if T != T2:
        raise ValueError(f"asset_returns has {T} rows but style_factors has {T2} rows")

    if factor_names is None:
        factor_names = list(style_factors.columns)

    time_index = asset_returns.index
    asset_cols = asset_returns.columns
    factor_returns_arr = np.zeros((T, K), dtype=np.float64)
    specific_returns_arr = np.zeros((T, N), dtype=np.float64)
    r_squared_arr = np.zeros(T, dtype=np.float64)

    X = style_factors.values.astype(np.float64)  # T x K factor exposures

    for t in range(T):
        r_t = asset_returns.iloc[t].values.astype(np.float64)  # N-vector
        x_t = X[t]  # K-vector (factor exposures at time t, same for all assets)

        # OLS: regress r_t (N-vector) on x_t (K-vector) using rank-1 design
        # Each asset i: r_i = x_t @ f_t + e_i
        # => f_t = (x_t' x_t)^{-1} x_t' r_t (scalar case if K=1)
        # => f_t = (X_t' X_t)^{-1} X_t' r_t where X_t = ones(N,1) * x_t
        # But that's just using x_t as the cross-sectional factor exposure for all assets
        # Standard Barra: X_t is N x K (each row is asset i's exposure to K factors at t)
        # For simplicity: exposure = x_t broadcast to all N assets
        # => design matrix D = ones(N,1) * x_t.T = same row x_t for every asset
        # => OLS: f_t = pinv(x_t * ones(N)) @ r_t ... but that's underdetermined for N>K

        # Correct interpretation: style_factors[t] is the factor exposure at time t.
        # For cross-sectional regression, we need an N x K matrix.
        # Broadcast: each asset has the same exposure x_t at time t.
        # This gives f_t = (x_t' x_t * N)^{-1} * (N * x_t' * mean_r_t) = x_t' * mean_r_t / ||x_t||^2
        # which simplifies to: project r onto x_t direction.

        # Alternatively: treat cross-sectional as r = X_t @ f_t where X_t = diag(x_t) * ones
        # Standard approach: use lstsq with X_t = tile(x_t, (N, 1)) transposed
        # => equivalent to ordinary least squares on the scatter plot (r_i vs x_t exposures)
        # with the same exposure for each asset at time t, we use x_t as the regressor

        # Design matrix: each asset i gets row x_t (K exposures, same for all assets at t)
        D = np.tile(x_t, (N, 1))  # N x K

        if cross_sectional_regression:
            # OLS: min ||r_t - D @ f_t||^2
            f_t, _, _, _ = np.linalg.lstsq(D, r_t, rcond=None)
        else:
            # Simple mean of returns as factor return
            f_t = np.full(K, float(np.mean(r_t)))

        e_t = r_t - D @ f_t

        factor_returns_arr[t] = f_t
        specific_returns_arr[t] = e_t

        # R-squared
        y_mean = float(np.mean(r_t))
        ss_tot = float(np.sum((r_t - y_mean) ** 2))
        ss_res = float(np.sum(e_t**2))
        r_sq = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        r_squared_arr[t] = r_sq

    factor_returns_df = pd.DataFrame(factor_returns_arr, index=time_index, columns=factor_names)
    specific_returns_df = pd.DataFrame(specific_returns_arr, index=time_index, columns=asset_cols)
    mean_r_squared = float(np.mean(r_squared_arr))

    return {
        "factor_returns": factor_returns_df,
        "specific_returns": specific_returns_df,
        "r_squared_per_period": r_squared_arr,
        "mean_r_squared": mean_r_squared,
    }
