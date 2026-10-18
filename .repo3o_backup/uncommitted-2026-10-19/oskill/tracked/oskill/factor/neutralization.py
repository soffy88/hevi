"""Factor neutralization: remove factor exposure from a signal."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def factor_neutralization(
    signal: np.ndarray | pd.Series,
    factor_exposures: pd.DataFrame,
    *,
    method: Literal["regression", "ranking"] = "regression",
    factors_to_neutralize: list[str] | None = None,
) -> np.ndarray | pd.Series:
    """Neutralize signal against factor exposures.

    Removes systematic factor variation from the signal, leaving only the
    component orthogonal to the specified factors. This prevents a signal from
    being rewarded merely for having factor exposure.

    regression:
        OLS regress signal on factor_exposures, return residuals.
        The residuals are uncorrelated with the factors by construction.

    ranking:
        Rank signal within factor quintile groups, then re-standardize to zero
        mean and unit variance. This provides a non-parametric neutralization.

    Args:
        signal: Asset signal vector (length N).
        factor_exposures: N x K DataFrame (assets x factors).
        method: 'regression' (default) or 'ranking'.
        factors_to_neutralize: Subset of factor_exposures columns to use.
                               If None, use all columns.

    Returns:
        Neutralized signal (same type and length as input).

    Raises:
        ValueError: If signal length doesn't match factor_exposures rows.
    """
    is_series = isinstance(signal, pd.Series)
    if is_series:
        sig = signal.values.astype(np.float64)
        sig_index = signal.index
    else:
        sig = np.asarray(signal, dtype=np.float64)
        sig_index = None

    N = len(sig)
    if len(factor_exposures) != N:
        raise ValueError(f"signal length {N} != factor_exposures rows {len(factor_exposures)}")

    # Select columns
    if factors_to_neutralize is not None:
        fe = factor_exposures[factors_to_neutralize].values.astype(np.float64)
    else:
        fe = factor_exposures.values.astype(np.float64)

    if method == "regression":
        # OLS: signal = fe @ betas + residuals
        # Design matrix includes intercept
        X = np.column_stack([np.ones(N), fe])
        coeffs, _, _, _ = np.linalg.lstsq(X, sig, rcond=None)
        y_hat = X @ coeffs
        residuals = sig - y_hat
        result = residuals

    elif method == "ranking":
        # Use first factor for quintile grouping (or mean if multiple)
        if fe.shape[1] > 1:
            # Use PC1 for grouping
            combined = np.mean(fe, axis=1)
        else:
            combined = fe[:, 0]

        # Create quintile groups
        n_groups = 5
        group_labels = pd.qcut(combined, q=n_groups, labels=False, duplicates="drop")

        result = np.zeros(N, dtype=np.float64)
        unique_groups = np.unique(group_labels[~pd.isna(group_labels)])
        for g in unique_groups:
            mask = group_labels == g
            if np.sum(mask) < 2:
                result[mask] = sig[mask]
                continue
            ranked = pd.Series(sig[mask]).rank(pct=True).values - 0.5
            # Standardize to zero mean, unit variance
            result[mask] = ranked / (np.std(ranked) + 1e-8)

        # Fill NaN groups
        nan_mask = pd.isna(group_labels)
        if np.any(nan_mask):
            result[nan_mask] = sig[nan_mask]

        # Re-standardize whole signal
        std_all = np.std(result)
        if std_all > 1e-8:
            result = (result - np.mean(result)) / std_all
    else:
        raise ValueError(f"Unknown method: {method!r}")

    if is_series:
        return pd.Series(result, index=sig_index)
    return result
