"""Fractional differentiation (Hosking 1981, López de Prado 2018 Ch.5)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def fractional_differentiation(
    series: np.ndarray | pd.Series,
    *,
    d: float = 0.5,
    threshold: float = 1e-5,
    method: Literal["standard", "fixed_width"] = "fixed_width",
    fixed_width: int | None = None,
) -> np.ndarray | pd.Series:
    """Fractional differentiation (Hosking 1981, López de Prado 2018 Ch.5).

    Fractional differencing with parameter d allows control over the degree
    of memory in the series: d=0 leaves the series unchanged, d=1 produces
    a first difference, and 0<d<1 provides a spectrum in between.

    Weights (binomial expansion of (1-B)^d):
    w_0 = 1, w_k = w_{k-1} * (k-1-d) / k  for k >= 1
    Equivalently: w_k = (-1)^k * C(d, k)

    The weights decrease in magnitude geometrically and are truncated when
    |w_k| < threshold (fixed_width method).

    Args:
        series: Input time series (length T).
        d: Fractional differencing parameter (default 0.5).
        threshold: Weight truncation threshold (default 1e-5).
        method: 'fixed_width' (default) or 'standard'.
                'fixed_width': truncate at |w_k| < threshold.
                'standard': use same truncation but with full convolution.
        fixed_width: Override window width (number of lags). If None, determined
                     by threshold.

    Returns:
        Differenced series. Length = T - W where W = number of weights - 1.
        Returns same type as input (pd.Series or np.ndarray).

    Note:
        For d=0, returns original series (no differencing).
        For d=1, approximates first differences (within floating point precision).
    """
    is_series = isinstance(series, pd.Series)
    if is_series:
        index = series.index
        x = series.values.astype(np.float64)
    else:
        x = np.asarray(series, dtype=np.float64)
        index = None

    T = len(x)
    if T == 0:
        if is_series:
            return pd.Series(dtype=np.float64)
        return np.array([], dtype=np.float64)

    # For fixed_width method (default), cap the window size so we have at least
    # T/2 output observations. This mirrors the fixed-width approach in
    # López de Prado (2018) where a practical window is chosen.
    if fixed_width is not None:
        max_window = int(fixed_width)
    elif method == "fixed_width":
        # Cap so output has at least T//2 points; window <= T//2
        max_window = max(1, T // 2)
    else:
        # "standard": use threshold but still cap at T to avoid empty output
        max_window = T

    # Compute weights for (1-B)^d operator:
    # w_0 = 1, w_k = w_{k-1} * (k-1-d)/k  (gives w_1=-d, w_2=d*(d-1)/2, ...)
    # This matches the binomial expansion: (-1)^k * C(d,k)
    weights: list[float] = [1.0]
    w = 1.0
    k = 1
    while k <= max_window:
        w = w * (k - 1 - d) / k
        if abs(w) < threshold:
            break
        weights.append(w)
        k += 1

    W = np.array(weights)  # shape (window_size,)
    window_size = len(W)

    # Safety: clamp to T
    if window_size > T:
        window_size = T
        W = W[:window_size]

    # Convolve: result[i] = sum(W[k] * x[i-k] for k=0..window_size-1)
    # Valid output starts at index window_size-1
    n_out = T - window_size + 1
    result = np.zeros(n_out, dtype=np.float64)

    for i in range(n_out):
        t_start = i + window_size - 1
        # x[t_start], x[t_start-1], ..., x[t_start - window_size + 1]
        segment = x[t_start - window_size + 1 : t_start + 1][::-1]
        result[i] = float(np.dot(W, segment))

    if is_series:
        out_index = index[window_size - 1 :]
        return pd.Series(result, index=out_index)

    return result
