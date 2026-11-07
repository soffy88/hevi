"""Signal ensemble — multi-method aggregation of signal streams."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import numpy as np
import pandas as pd


def signal_ensemble(
    signals: dict[str, np.ndarray | pd.Series],
    weights: dict[str, float],
    *,
    decay_fn: Callable[[int], float] | None = None,
    decay_lookback: int = 0,
    aggregation: Literal["linear", "geometric", "harmonic"] = "linear",
) -> np.ndarray | pd.Series:
    """Ensemble multiple signal streams into a single signal.

    Mathematical definition:
        For each timestamp t:
            raw_score_t = aggregation_method(
                {name: signal[t] * weight[name] for name in signals}
            )
            decayed_score_t = raw_score_t * decay_fn(t_lag)  # if decay_fn given
            final_score_t = clip(decayed_score_t, -1, 1)

    Aggregation methods:
        linear:    sum(w_i * s_i) / sum(w_i)
        geometric: prod((s_i + 1)^w_i)^(1/sum(w_i)) - 1  (for signals in [-1, 1])
        harmonic:  1 / sum(w_i / s_i)  (for non-zero signals)

    Decay:
        If decay_fn is provided, apply multiplier at each position t.
        If decay_fn is None and decay_lookback > 0, uses linear decay:
            weight_t = max(0, 1 - t_lag / decay_lookback)
        decay_fn signature: (lag: int) -> float, where lag=0 = most recent.

    Returns aggregated signal of same length as input signals, clipped to [-1, 1].
    Output type matches the first signal's type (ndarray or pd.Series with same index).

    Reference: Carver (2015), "Systematic Trading", 3-layer forecast combination.
    Reference: López de Prado (2018), "Advances in Financial Machine Learning", Ch.16.

    Parameters
    ----------
    signals : dict
        Map of signal_name -> time-aligned array/Series, ideally in [-1, 1].
    weights : dict
        Non-negative weight per signal. Must contain all keys from signals.
    decay_fn : callable or None
        Optional (lag: int) -> float multiplier. Applied to output at each t.
    decay_lookback : int
        If > 0 and decay_fn is None, uses linear decay over lookback bars.
    aggregation : {'linear', 'geometric', 'harmonic'}
        Aggregation method.

    Returns
    -------
    np.ndarray or pd.Series clipped to [-1, 1].

    Raises
    ------
    ValueError
        If signals have mismatched lengths, weights are invalid, or
        weights dict doesn't cover all signal keys.
    """
    if not signals:
        raise ValueError("signals must not be empty")

    names = list(signals.keys())
    first = signals[names[0]]

    # --- Validate weights ---
    for key in names:
        if key not in weights:
            raise ValueError(f"Missing weight for signal '{key}'")
    for key, w in weights.items():
        if key not in signals:
            raise ValueError(f"Weight key '{key}' not found in signals")
        if w < 0:
            raise ValueError(f"Weight for '{key}' must be non-negative, got {w}")
    w_sum = sum(weights[k] for k in names)
    if w_sum == 0:
        raise ValueError("Sum of weights must be positive")

    # --- Convert to arrays, validate lengths ---
    arrays: dict[str, np.ndarray] = {}
    is_series = isinstance(first, pd.Series)
    idx = first.index if is_series else None
    n = len(first)
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

    # --- Normalized weights ---
    norm_w = {k: weights[k] / w_sum for k in names}

    # --- Aggregate ---
    if aggregation == "linear":
        combined = np.zeros(n)
        for name in names:
            combined += norm_w[name] * arrays[name]

    elif aggregation == "geometric":
        # Shift to [0, 2] for product, shift back
        log_combined = np.zeros(n)
        for name in names:
            shifted = arrays[name] + 1.0  # [0, 2]
            shifted = np.clip(shifted, 1e-10, None)  # avoid log(0)
            log_combined += norm_w[name] * np.log(shifted)
        combined = np.exp(log_combined) - 1.0

    elif aggregation == "harmonic":
        inv_combined = np.zeros(n)
        w_total = 0.0
        for name in names:
            nz = arrays[name] != 0
            inv_combined[nz] += norm_w[name] / arrays[name][nz]
            w_total += norm_w[name]
        with np.errstate(divide="ignore", invalid="ignore"):
            combined = np.where(inv_combined != 0, 1.0 / inv_combined, 0.0)

    else:
        raise ValueError(f"Unknown aggregation method: {aggregation!r}")

    # --- Apply decay ---
    effective_decay_fn = decay_fn
    if effective_decay_fn is None and decay_lookback > 0:

        def _linear_decay(lag: int) -> float:
            return max(0.0, 1.0 - lag / decay_lookback)

        effective_decay_fn = _linear_decay

    if effective_decay_fn is not None:
        for t in range(n):
            lag = n - 1 - t
            combined[t] *= effective_decay_fn(lag)

    # --- Clip to [-1, 1] ---
    combined = np.clip(combined, -1.0, 1.0)

    if is_series:
        return pd.Series(combined, index=idx)
    return combined
