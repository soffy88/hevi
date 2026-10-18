"""Signal detection workflows built on oprim primitives."""

from __future__ import annotations

import numpy as np


def adx(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """Average Directional Index with Wilder smoothing.

    Measures trend strength (0-100). ADX > 25 = trending.

    Parameters
    ----------
    highs, lows, closes : np.ndarray
        OHLC arrays (same length, at least period+1 bars).
    period : int
        Smoothing period (default 14).

    Returns
    -------
    float
        Current ADX value.

    References
    ----------
    .. [1] Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    .. [2] Extraction source: Selene project, services/signal/regime/detector.py:_calc_adx
    """
    n = len(closes)
    if n < period + 1:
        raise ValueError(f"Need at least {period + 1} bars, got {n}")

    # Directional movement
    plus_dm = np.zeros(n - 1)
    minus_dm = np.zeros(n - 1)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i - 1] = up
        if down > up and down > 0:
            minus_dm[i - 1] = down

    # True Range
    trs = np.empty(n - 1)
    for i in range(1, n):
        trs[i - 1] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    # Wilder smoothing helper
    def wilder_smooth(values: np.ndarray, n_period: int) -> np.ndarray:
        result = np.empty(len(values) - n_period + 1)
        result[0] = values[:n_period].sum()
        for i in range(1, len(result)):
            result[i] = result[i - 1] - result[i - 1] / n_period + values[n_period - 1 + i]
        return result

    sm_tr = wilder_smooth(trs, period)
    sm_plus = wilder_smooth(plus_dm, period)
    sm_minus = wilder_smooth(minus_dm, period)

    # +DI, -DI
    plus_di = 100 * sm_plus / np.where(sm_tr > 0, sm_tr, 1.0)
    minus_di = 100 * sm_minus / np.where(sm_tr > 0, sm_tr, 1.0)

    # DX
    di_sum = plus_di + minus_di
    dx = 100 * np.abs(plus_di - minus_di) / np.where(di_sum > 0, di_sum, 1.0)

    if len(dx) < period:
        return float(dx[-1]) if len(dx) > 0 else 0.0

    # ADX = Wilder smooth of DX
    adx_val = float(dx[:period].mean())
    for d in dx[period:]:
        adx_val = (adx_val * (period - 1) + d) / period
    return adx_val


def cusum_detector(
    z_scores: np.ndarray,
    threshold: float = 2.0,
    drift: float = 0.0,
) -> dict[str, np.ndarray | list[int]]:
    """Page's CUSUM change-point detector (two-sided).

    Accumulates positive and negative deviations; signals when
    cumulative sum exceeds threshold.

    Parameters
    ----------
    z_scores : np.ndarray
        Standardized input series.
    threshold : float
        Detection threshold (default 2.0 sigma-equivalents).
    drift : float
        Allowance / slack parameter (default 0 = no drift correction).

    Returns
    -------
    dict
        "pos_cusum": positive accumulator series,
        "neg_cusum": negative accumulator series,
        "signals": list of indices where threshold was breached.

    References
    ----------
    .. [1] Page, E.S. (1954). Continuous inspection schemes.
    .. [2] Extraction source: Selene project, sel_v2/strategies/cusum_short.py:CUSUMShort.update
    """
    n = len(z_scores)
    pos = np.zeros(n)
    neg = np.zeros(n)
    signals = []

    for i in range(1, n):
        pos[i] = max(0.0, pos[i - 1] + z_scores[i] - drift)
        neg[i] = max(0.0, neg[i - 1] - z_scores[i] - drift)
        if pos[i] > threshold or neg[i] > threshold:
            signals.append(i)
            pos[i] = 0.0
            neg[i] = 0.0

    return {"pos_cusum": pos, "neg_cusum": neg, "signals": signals}


def platt_calibration(
    scores: np.ndarray,
    outcomes: np.ndarray,
    n_grid: int = 20,
) -> dict[str, float]:
    """Platt scaling (sigmoid calibration) via grid search.

    Fits P(y=1|s) = 1 / (1 + exp(-(s - center) * scale))

    Parameters
    ----------
    scores : np.ndarray
        Raw model scores.
    outcomes : np.ndarray
        Binary outcomes (0 or 1).
    n_grid : int
        Grid search resolution per parameter.

    Returns
    -------
    dict
        "center": optimal center, "scale": optimal scale,
        "log_loss": best log-loss achieved.

    References
    ----------
    .. [1] Platt, J. (1999). Probabilistic outputs for SVMs.
    .. [2] Extraction source: Selene project, services/signal/factors/composite.py:platt_fit
    """
    scores = np.asarray(scores, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    if len(scores) < 10:
        return {"center": 0.0, "scale": 1.0, "log_loss": float("inf")}

    best_loss = float("inf")
    best_center = 0.0
    best_scale = 1.0

    centers = np.linspace(float(scores.min()), float(scores.max()), n_grid)
    scales = np.linspace(0.5, 5.0, n_grid)

    for c in centers:
        for s in scales:
            probs = 1.0 / (1.0 + np.exp(-(scores - c) * s))
            probs = np.clip(probs, 1e-10, 1 - 1e-10)
            loss = -np.mean(outcomes * np.log(probs) + (1 - outcomes) * np.log(1 - probs))
            if loss < best_loss:
                best_loss = loss
                best_center = float(c)
                best_scale = float(s)

    return {"center": best_center, "scale": best_scale, "log_loss": float(best_loss)}
