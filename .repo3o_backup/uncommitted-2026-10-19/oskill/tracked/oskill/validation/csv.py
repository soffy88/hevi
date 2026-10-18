"""Combinatorially Symmetric Cross-Validation (Bailey et al. 2017)."""

from __future__ import annotations

import itertools
import random
from typing import Any

import numpy as np
import pandas as pd


def combinatorially_symmetric_cv(
    backtest_returns_matrix: np.ndarray | pd.DataFrame,
    *,
    n_splits: int = 16,
    metric: str = "sharpe",
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Combinatorially Symmetric Cross-Validation (CSCV).

    Unlike PBO, CSCV ensures each strategy appears in both IS and OOS roles
    across all C(S, S/2) combinations, yielding a more exhaustive estimate of
    overfitting probability.

    Algorithm (Bailey et al. 2017):
        1. Split T observations into S equal subsets (S = n_splits, must be even)
        2. For each C(S, S/2) combination of S/2 "in-sample" subsets:
           a. IS = rows from chosen S/2 subsets; OOS = remaining S/2 subsets
           b. Compute metric per strategy on IS, find best strategy
           c. Rank best strategy on OOS; compute rank logit
        3. CSCV PBO = fraction of combos where rank_logit < 0
        4. performance_degradation = mean(OOS_metric_best - IS_metric_best)
        5. haircut_to_apply derived from mean(rank_logits)

    Combos limited to 500 random samples when C(S, S/2) > 500.

    Args:
        backtest_returns_matrix: T x N matrix (T observations, N strategies).
        n_splits: Number of equal subsets S (must be even, >= 4).
        metric: Performance metric — only "sharpe" supported.
        confidence: Unused confidence level (reserved for future use).

    Returns:
        cscv_pbo: float in [0, 1]
        rank_logits: np.ndarray
        is_overfit: bool (cscv_pbo > 0.5)
        performance_degradation_pct: float percentage
        haircut_to_apply: float in [0, 1]

    Reference:
        Bailey et al. (2017).
    """
    if isinstance(backtest_returns_matrix, pd.DataFrame):
        data = backtest_returns_matrix.values.astype(np.float64)
    else:
        data = np.asarray(backtest_returns_matrix, dtype=np.float64)

    T, N = data.shape

    if n_splits % 2 != 0:
        raise ValueError(f"n_splits must be even, got {n_splits}")
    if n_splits < 4:
        raise ValueError(f"n_splits must be >= 4, got {n_splits}")
    if T < n_splits:
        raise ValueError(f"T={T} must be >= n_splits={n_splits}")
    if N < 2:
        raise ValueError(f"Need at least 2 strategies, got N={N}")

    bin_size = T // n_splits
    bins: list[np.ndarray] = []
    for i in range(n_splits):
        start = i * bin_size
        end = start + bin_size if i < n_splits - 1 else T
        bins.append(np.arange(start, end))

    half = n_splits // 2
    all_combos = list(itertools.combinations(range(n_splits), half))
    if len(all_combos) > 500:
        rng_state = random.Random(42)
        all_combos = rng_state.sample(all_combos, 500)

    def _sharpe(mat: np.ndarray) -> np.ndarray:
        means = mat.mean(axis=0)
        stds = mat.std(axis=0, ddof=1)
        stds = np.where(stds < 1e-10, 1e-10, stds)
        return means / stds * np.sqrt(252)

    rank_logits: list[float] = []
    perf_deltas: list[float] = []

    for is_bins in all_combos:
        is_set = set(is_bins)
        oos_bins = [b for b in range(n_splits) if b not in is_set]

        is_idx = np.concatenate([bins[b] for b in is_bins])
        oos_idx = np.concatenate([bins[b] for b in oos_bins])

        is_sharpes = _sharpe(data[is_idx])
        oos_sharpes = _sharpe(data[oos_idx])

        best = int(np.argmax(is_sharpes))
        best_is = float(is_sharpes[best])
        best_oos = float(oos_sharpes[best])

        rank = int(np.sum(oos_sharpes <= best_oos))
        rank_clipped = float(np.clip(rank, 1, N - 1))
        logit = float(np.log(rank_clipped / (N - rank_clipped)))
        rank_logits.append(logit)
        perf_deltas.append(best_oos - best_is)

    logits_arr = np.array(rank_logits)
    cscv_pbo = float(np.mean(logits_arr < 0))

    mean_logit = float(np.mean(logits_arr))
    # Map mean_logit to haircut: negative logit → more haircut, range [0, 1]
    haircut = float(np.clip(1.0 / (1.0 + np.exp(mean_logit)) - 0.5, 0.0, 1.0))

    perf_deg_pct = float(np.mean(perf_deltas)) * 100.0

    return {
        "cscv_pbo": cscv_pbo,
        "rank_logits": logits_arr,
        "is_overfit": cscv_pbo > 0.5,
        "performance_degradation_pct": perf_deg_pct,
        "haircut_to_apply": haircut,
    }
