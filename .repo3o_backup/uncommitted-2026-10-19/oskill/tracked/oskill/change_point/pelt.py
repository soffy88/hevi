"""PELT (Pruned Exact Linear Time) change point detection (Killick et al. 2012)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd


def _cost_mean(x: np.ndarray, start: int, end: int) -> float:
    """Sum of squared deviations from segment mean."""
    seg = x[start:end]
    if len(seg) == 0:
        return 0.0
    mu = np.mean(seg)
    return float(np.sum((seg - mu) ** 2))


def _cost_variance(x: np.ndarray, start: int, end: int, global_mean: float) -> float:
    """Sum of squared deviations from global mean (tests for variance changes)."""
    seg = x[start:end]
    if len(seg) == 0:
        return 0.0
    return float(np.sum((seg - global_mean) ** 2))


def _cost_normal(x: np.ndarray, start: int, end: int) -> float:
    """Negative twice log-likelihood under Gaussian (both mean and variance)."""
    seg = x[start:end]
    n = len(seg)
    if n <= 1:
        return 0.0
    np.mean(seg)
    var = np.var(seg)
    if var <= 0:
        var = 1e-10
    return float(n * np.log(var) + n)  # -2 * loglik up to constant


def pelt_change_point(
    series: np.ndarray | pd.Series,
    *,
    penalty: float | None = None,
    model: Literal["mean", "variance", "normal"] = "normal",
    min_segment_length: int = 5,
    penalty_method: Literal["bic", "aic", "manual"] = "bic",
) -> dict[str, Any]:
    """PELT (Pruned Exact Linear Time) change point detection.

    Finds optimal change points minimizing: sum of costs + penalty * n_changepoints.

    Cost functions:
        - "mean": sum of (x - segment_mean)^2
        - "variance": sum of (x - overall_mean)^2 (tests for variance changes)
        - "normal": -2 * log-likelihood under Gaussian (both mean & variance)

    The PELT algorithm uses dynamic programming with pruning to achieve
    O(n) average complexity.

    Args:
        series: Univariate time series (length T).
        penalty: Manual penalty value (overrides penalty_method if provided).
        model: Cost model — 'mean', 'variance', or 'normal' (default).
        min_segment_length: Minimum segment length in samples (default 5).
        penalty_method: Automatic penalty — 'bic' (default), 'aic', or 'manual'.

    Returns dict:
        - 'change_points': list of int (end indices of segments, excluding last)
        - 'n_segments': int
        - 'segment_means': list of float
        - 'segment_variances': list of float
        - 'total_cost': float

    Reference:
        Killick, R., Fearnhead, P. & Eckley, I.A. (2012). "Optimal Detection of
        Changepoints with a Linear Computational Cost." JASA 107(500):1590-1598.
    """
    if isinstance(series, pd.Series):
        x = series.values.astype(np.float64)
    else:
        x = np.asarray(series, dtype=np.float64)

    T = len(x)
    if T < 2 * min_segment_length:
        # Not enough data for any change point
        return {
            "change_points": [],
            "n_segments": 1,
            "segment_means": [float(np.mean(x))],
            "segment_variances": [float(np.var(x))],
            "total_cost": 0.0,
        }

    # Determine penalty
    if penalty is not None:
        pen = float(penalty)
    else:
        n_params = 1 if model == "mean" else (1 if model == "variance" else 2)
        if penalty_method == "bic":
            pen = n_params * np.log(T)
        elif penalty_method == "aic":
            pen = 2.0 * n_params
        else:
            pen = n_params * np.log(T)  # default to BIC for 'manual' without penalty

    global_mean = float(np.mean(x)) if model == "variance" else 0.0

    # Build cost function
    def cost(start: int, end: int) -> float:
        if model == "mean":
            return _cost_mean(x, start, end)
        elif model == "variance":
            return _cost_variance(x, start, end, global_mean)
        else:
            return _cost_normal(x, start, end)

    # PELT dynamic programming
    # F[t] = min cost of segmenting x[0:t]
    # cp[t] = last change point before t
    INF = float("inf")
    F = np.full(T + 1, INF)
    F[0] = -pen  # Base case: F[0] = 0 - penalty (so F[t] = F[0]+cost+pen works)
    cp = np.full(T + 1, -1, dtype=np.int32)

    # Candidate set (PELT pruning)
    candidates: list[int] = [0]

    for t in range(min_segment_length, T + 1):
        best_cost = INF
        best_prev = -1

        for s in candidates:
            seg_end = t
            seg_start = s
            seg_len = seg_end - seg_start
            if seg_len < min_segment_length:
                continue
            c = F[s] + cost(seg_start, seg_end) + pen
            if c < best_cost:
                best_cost = c
                best_prev = s

        F[t] = best_cost
        cp[t] = best_prev

        # PELT pruning: remove s if F[s] + cost(s,t) + pen > F[t]
        # (they can never be optimal for any future t' > t)
        new_candidates: list[int] = []
        for s in candidates:
            seg_len = t - s
            if seg_len < min_segment_length:
                new_candidates.append(s)  # keep, might be valid later
                continue
            c_prune = F[s] + cost(s, t)
            if c_prune <= F[t]:
                new_candidates.append(s)
        # Add t as a new candidate if there's room for another segment
        if T - t >= min_segment_length:
            new_candidates.append(t)
        candidates = new_candidates

    # Backtrack change points
    change_points: list[int] = []
    t = T
    while t > 0:
        prev = cp[t]
        if prev < 0:
            break
        if prev > 0:
            change_points.append(prev)
        t = prev
    change_points.reverse()

    # Build segments
    boundaries = [0] + change_points + [T]
    segment_means: list[float] = []
    segment_variances: list[float] = []
    for i in range(len(boundaries) - 1):
        seg = x[boundaries[i] : boundaries[i + 1]]
        segment_means.append(float(np.mean(seg)) if len(seg) > 0 else 0.0)
        segment_variances.append(float(np.var(seg)) if len(seg) > 0 else 0.0)

    total_cost = float(F[T]) - pen  # remove base penalty offset

    return {
        "change_points": change_points,
        "n_segments": len(boundaries) - 1,
        "segment_means": segment_means,
        "segment_variances": segment_variances,
        "total_cost": total_cost,
    }
