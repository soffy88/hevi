"""Probability of Backtest Overfitting (Bailey et al., 2015)."""

from __future__ import annotations

import itertools
import random
from math import comb
from typing import Any

import numpy as np
import oprim
import pandas as pd


def probability_of_backtest_overfitting(
    backtest_returns_matrix: np.ndarray | pd.DataFrame,
    *,
    n_splits: int = 16,
    metric: str = "sharpe",
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """Probability of Backtest Overfitting (PBO).

    Implements the CSCV (Combinatorially Symmetric Cross-Validation) method
    from Bailey et al. (2015).

    Algorithm:
        1. Split T rows into n_splits equal bins
        2. For each combination of n_splits//2 bins as training:
           - Compute metric (Sharpe) for each strategy on training and test bins
           - Identify best strategy on training
           - Compute rank of best strategy on test bins
           - If rank < N/2: overfitting for this split
        3. PBO = fraction of splits where best-train ranks < median in test

    Returns dict:
        pbo:                    float in [0, 1]
        rank_logits:            np.ndarray of log(rank / (N - rank))
        performance_degradation: float mean(test_sharpe_best - train_sharpe_best)
        is_significant_overfit: bool (PBO > 0.55)

    Reference:
        Bailey et al. (2015), "The Probability of Backtest Overfitting"
        Journal of Computational Finance.

    Args:
        backtest_returns_matrix: T x N matrix (T observations, N strategies).
        n_splits: Number of equal bins (must be even, >= 2).
        metric: Performance metric (only "sharpe" supported).
        risk_free_rate: Risk-free rate for Sharpe computation.

    Raises:
        ValueError: If n_splits is odd, T < n_splits, or N < 2.
    """
    # Handle DataFrame input
    if isinstance(backtest_returns_matrix, pd.DataFrame):
        data = backtest_returns_matrix.values.astype(np.float64)
    else:
        data = np.asarray(backtest_returns_matrix, dtype=np.float64)

    T, N = data.shape

    # Validate inputs
    if n_splits % 2 != 0:
        raise ValueError(f"n_splits must be even, got {n_splits}")
    if n_splits < 2:
        raise ValueError(f"n_splits must be >= 2, got {n_splits}")
    if T < n_splits:
        raise ValueError(f"T={T} must be >= n_splits={n_splits}")
    if N < 2:
        raise ValueError(f"Need at least 2 strategies, got N={N}")

    # Split T rows into n_splits equal bins
    bin_size = T // n_splits
    bins = []
    for i in range(n_splits):
        start = i * bin_size
        end = start + bin_size if i < n_splits - 1 else T
        bins.append(np.arange(start, end))

    n_train_bins = n_splits // 2
    all_bin_indices = list(range(n_splits))

    def _compute_sharpe(rets_matrix: np.ndarray) -> np.ndarray:
        """Compute Sharpe for each strategy (column)."""
        sharpes = np.zeros(N)
        for j in range(N):
            col = rets_matrix[:, j]
            s = oprim.sharpe_ratio(pd.Series(col), risk_free_rate=risk_free_rate)
            sharpes[j] = float(s)
        return sharpes

    # Enumerate combinations (limit to 500 random samples if too many)
    total_combos = comb(n_splits, n_train_bins)
    max_combos = 500
    all_combos = list(itertools.combinations(all_bin_indices, n_train_bins))
    if total_combos > max_combos:
        random.seed(42)
        sampled_combos = random.sample(all_combos, max_combos)
    else:
        sampled_combos = all_combos

    overfit_count = 0
    rank_logits = []
    perf_degradations = []

    for train_bins in sampled_combos:
        train_bins_set = set(train_bins)
        test_bins_list = [i for i in all_bin_indices if i not in train_bins_set]

        # Build train and test data
        train_idx = np.concatenate([bins[b] for b in train_bins])
        test_idx = np.concatenate([bins[b] for b in test_bins_list])

        train_data = data[train_idx]
        test_data = data[test_idx]

        # Compute Sharpe for each strategy
        train_sharpes = _compute_sharpe(train_data)
        test_sharpes = _compute_sharpe(test_data)

        # Best strategy on training set
        best_train_idx = int(np.argmax(train_sharpes))
        best_train_sharpe = float(train_sharpes[best_train_idx])

        # Rank of best strategy on test set (1 = worst, N = best)
        # rank = number of strategies with test_sharpe <= best_strategy's test_sharpe
        best_test_sharpe = float(test_sharpes[best_train_idx])
        rank = int(np.sum(test_sharpes <= best_test_sharpe))

        # Overfitting: best on train is below median on test
        if rank < N / 2:
            overfit_count += 1

        # Logit of normalized rank
        # Normalize rank to (0, 1) avoiding 0 and N
        rank_normalized = float(rank) / float(N)
        # Clip to avoid log(0)
        rank_normalized = np.clip(rank_normalized, 1e-6, 1 - 1e-6)
        logit = float(np.log(rank_normalized / (1.0 - rank_normalized)))
        rank_logits.append(logit)

        # Performance degradation: test_sharpe - train_sharpe for best strategy
        perf_degradations.append(best_test_sharpe - best_train_sharpe)

    n_splits_used = len(sampled_combos)
    pbo = float(overfit_count) / float(n_splits_used)

    return {
        "pbo": pbo,
        "rank_logits": np.array(rank_logits),
        "performance_degradation": float(np.mean(perf_degradations)),
        "is_significant_overfit": pbo > 0.55,
    }
