"""Fama-French 5-factor model OLS regression."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

_FF5_FACTORS = ["MKT", "SMB", "HML", "RMW", "CMA"]


def fama_french_5_factor_model(
    asset_returns: np.ndarray | pd.Series,
    factor_returns: pd.DataFrame,
    *,
    factors: list[str] | None = None,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """Fama-French 5-factor model OLS regression.

    R_i - Rf = alpha + beta_MKT*MKT + beta_SMB*SMB + beta_HML*HML
              + beta_RMW*RMW + beta_CMA*CMA + e

    OLS via numpy.linalg.lstsq.
    t-stats: beta / std_error where std_error = sqrt(diag(sigma^2 * (X'X)^{-1}))

    Args:
        asset_returns: Asset return series (length T).
        factor_returns: DataFrame with columns matching factors list (T x K).
        factors: Factor names to use (default: ['MKT', 'SMB', 'HML', 'RMW', 'CMA']).
        risk_free_rate: Risk-free rate to subtract from asset_returns (default 0).

    Returns dict:
        - 'alpha': float
        - 'betas': dict {factor: beta}
        - 'beta_t_stats': dict {factor: t_stat}
        - 'alpha_t_stat': float
        - 'r_squared': float
        - 'adjusted_r_squared': float
        - 'residual_std': float
        - 'n_obs': int
    """
    if factors is None:
        factors = _FF5_FACTORS

    if isinstance(asset_returns, pd.Series):
        y = asset_returns.values.astype(np.float64)
    else:
        y = np.asarray(asset_returns, dtype=np.float64)

    y = y - float(risk_free_rate)

    # Build design matrix with intercept
    X_cols = []
    for f in factors:
        if f not in factor_returns.columns:
            raise ValueError(
                f"Factor '{f}' not found in factor_returns columns: {list(factor_returns.columns)}"
            )
        X_cols.append(factor_returns[f].values.astype(np.float64))

    T = len(y)
    K = len(factors)

    X = np.column_stack([np.ones(T)] + X_cols)  # shape (T, K+1)

    if T != X.shape[0]:
        raise ValueError(f"asset_returns length {T} != factor_returns length {X.shape[0]}")

    # OLS: solve X @ beta = y
    coeffs, residuals_sum, rank, sv = np.linalg.lstsq(X, y, rcond=None)

    alpha = float(coeffs[0])
    betas = {f: float(coeffs[i + 1]) for i, f in enumerate(factors)}

    y_pred = X @ coeffs
    residuals = y - y_pred
    n_params = K + 1  # alpha + K betas

    # Residual variance
    dof = T - n_params
    if dof > 0:
        sigma2 = float(np.sum(residuals**2) / dof)
    else:
        sigma2 = float(np.var(residuals)) if len(residuals) > 0 else 0.0

    residual_std = float(np.sqrt(sigma2))

    # Covariance matrix of coefficients: sigma^2 * (X'X)^{-1}
    XtX = X.T @ X
    try:
        XtX_inv = np.linalg.inv(XtX)
        var_coeffs = sigma2 * XtX_inv
        se = np.sqrt(np.maximum(np.diag(var_coeffs), 0.0))
    except np.linalg.LinAlgError:
        se = np.zeros(n_params)

    alpha_t_stat = float(coeffs[0] / se[0]) if se[0] > 0 else 0.0
    beta_t_stats = {
        f: float(coeffs[i + 1] / se[i + 1]) if se[i + 1] > 0 else 0.0 for i, f in enumerate(factors)
    }

    # R-squared
    y_mean = float(np.mean(y))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    ss_res = float(np.sum(residuals**2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    adjusted_r_squared = 1.0 - (1.0 - r_squared) * (T - 1) / (T - n_params) if T > n_params else 0.0

    return {
        "alpha": alpha,
        "betas": betas,
        "beta_t_stats": beta_t_stats,
        "alpha_t_stat": alpha_t_stat,
        "r_squared": float(r_squared),
        "adjusted_r_squared": float(adjusted_r_squared),
        "residual_std": residual_std,
        "n_obs": T,
    }
