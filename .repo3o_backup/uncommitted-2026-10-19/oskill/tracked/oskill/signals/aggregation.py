"""Weighted signal aggregation — Carver's 3-layer forecast combination."""

from __future__ import annotations

import numpy as np
import pandas as pd


def weighted_signal_aggregation(
    signals: dict[str, np.ndarray | pd.Series],
    raw_weights: dict[str, float],
    *,
    shrinkage: float = 0.7,
    correlation_matrix: np.ndarray | pd.DataFrame | None = None,
    apply_fdm: bool = True,
) -> dict[str, np.ndarray | pd.Series | float]:
    """Carver's 3-layer forecast combination with shrinkage + FDM.

    Mathematical definition (Carver, 2015, Chapter 8):
        Step 1: Shrink raw weights toward equal weights
            equal_weight = 1 / N
            shrunk_w_i = (1 - shrinkage) * raw_w_i + shrinkage * equal_weight
            Then normalize so shrunk weights sum to 1.

        Step 2: Compute Forecast Diversification Multiplier (FDM)
            FDM = 1 / sqrt(w^T * Sigma * w)
            where Sigma is the signal correlation matrix (N x N).
            If correlation_matrix is None, estimated from signals via pandas .corr().
            If apply_fdm is False, FDM = 1.0.

        Step 3: Final combined signal
            combined_t = sum(shrunk_w_i * signal_i_t) * FDM
            combined_t = clip(combined_t, -2, 2)

    Returns dict with keys:
        - 'combined': final combined signal array/Series (same length/index as inputs)
        - 'shrunk_weights': dict[str, float] of normalized shrunk weights
        - 'fdm': float, the Forecast Diversification Multiplier

    Reference: Carver (2015), "Systematic Trading", Chapter 8, "Combining Signals".
    Reference: Carver (2019), "Leveraged Trading", Appendix B, diversification multiplier.

    Parameters
    ----------
    signals : dict
        Map of signal_name -> time-aligned array/Series, each ideally in [-1, 1].
    raw_weights : dict
        Non-negative weight per signal. Keys must match signals exactly.
    shrinkage : float
        Shrinkage coefficient in [0, 1]. 0 = no shrinkage (use raw weights).
        1 = full shrinkage (equal weights). Carver recommends 0.7.
    correlation_matrix : ndarray, DataFrame, or None
        N×N correlation matrix. If None, estimated from signals. Must be symmetric,
        diagonal=1, positive semi-definite.
    apply_fdm : bool
        If True (default), apply FDM scaling. If False, FDM = 1.0.

    Returns
    -------
    dict with 'combined', 'shrunk_weights', 'fdm'.

    Raises
    ------
    ValueError
        If signals are empty, weights are invalid, shrinkage out of [0,1],
        or correlation_matrix fails validation.
    """
    if not signals:
        raise ValueError("signals must not be empty")

    names = list(signals.keys())
    n_signals = len(names)
    first = signals[names[0]]

    # --- Validate weights ---
    for key in names:
        if key not in raw_weights:
            raise ValueError(f"Missing weight for signal '{key}'")
    for key, w in raw_weights.items():
        if key not in signals:
            raise ValueError(f"Weight key '{key}' not found in signals")
        if w < 0:
            raise ValueError(f"Weight for '{key}' must be non-negative, got {w}")
    if sum(raw_weights[k] for k in names) == 0:
        raise ValueError("Sum of raw_weights must be positive")

    # --- Validate shrinkage ---
    if not (0.0 <= shrinkage <= 1.0):
        raise ValueError(f"shrinkage must be in [0, 1], got {shrinkage}")

    # --- Convert signals to arrays, validate lengths ---
    is_series = isinstance(first, pd.Series)
    idx = first.index if is_series else None
    n = len(first)
    arrays: dict[str, np.ndarray] = {}
    for name in names:
        arr = np.asarray(signals[name], dtype=float)
        if len(arr) != n:
            raise ValueError(f"Signal '{name}' length {len(arr)} != expected {n}")
        if is_series and isinstance(signals[name], pd.Series):
            if not signals[name].index.equals(idx):
                raise ValueError(
                    f"Signal '{name}' has different pandas index than the first signal"
                )
        arrays[name] = arr

    # --- Step 1: Shrink weights ---
    equal_w = 1.0 / n_signals
    raw_sum = sum(raw_weights[k] for k in names)
    normalized_raw = {k: raw_weights[k] / raw_sum for k in names}
    shrunk: dict[str, float] = {
        k: (1.0 - shrinkage) * normalized_raw[k] + shrinkage * equal_w for k in names
    }
    # Renormalize (shrinkage of normalized weights sums to 1 by construction, but guard fp)
    shrunk_sum = sum(shrunk.values())
    shrunk_weights: dict[str, float] = {k: v / shrunk_sum for k, v in shrunk.items()}

    # --- Step 2: FDM ---
    if apply_fdm:
        sigma = _get_correlation_matrix(arrays, names, correlation_matrix)
        w_vec = np.array([shrunk_weights[k] for k in names])
        quad = float(w_vec @ sigma @ w_vec)
        fdm = 1.0 / np.sqrt(max(quad, 1e-14))
    else:
        fdm = 1.0

    # --- Step 3: Combine ---
    combined = np.zeros(n)
    for name in names:
        combined += shrunk_weights[name] * arrays[name]
    combined *= fdm
    combined = np.clip(combined, -2.0, 2.0)

    if is_series:
        combined_out: np.ndarray | pd.Series = pd.Series(combined, index=idx)
    else:
        combined_out = combined

    return {
        "combined": combined_out,
        "shrunk_weights": shrunk_weights,
        "fdm": fdm,
    }


def _get_correlation_matrix(
    arrays: dict[str, np.ndarray],
    names: list[str],
    provided: np.ndarray | pd.DataFrame | None,
) -> np.ndarray:
    """Return validated N×N correlation matrix."""
    n = len(names)

    if provided is not None:
        sigma = np.asarray(provided, dtype=float)
        if sigma.shape != (n, n):
            raise ValueError(f"correlation_matrix shape {sigma.shape} != ({n}, {n})")
        if not np.allclose(sigma, sigma.T, atol=1e-8):
            raise ValueError("correlation_matrix must be symmetric")
        if not np.allclose(np.diag(sigma), 1.0, atol=1e-8):
            raise ValueError("correlation_matrix diagonal must be 1")
        eigvals = np.linalg.eigvalsh(sigma)
        if eigvals.min() < -1e-8:
            raise ValueError(
                f"correlation_matrix is not positive semi-definite "
                f"(min eigenvalue={eigvals.min():.6g})"
            )
        return sigma

    # Estimate from signals using pandas
    df = pd.DataFrame({name: arrays[name] for name in names})
    sigma_df = df.corr()
    sigma = sigma_df.values.astype(float)

    # Fill NaN diagonal entries (constant signals have NaN corr)
    np.fill_diagonal(sigma, 1.0)
    # Fill remaining NaN off-diagonal with 0 (uncorrelated assumption)
    sigma = np.nan_to_num(sigma, nan=0.0)
    np.fill_diagonal(sigma, 1.0)

    return sigma
