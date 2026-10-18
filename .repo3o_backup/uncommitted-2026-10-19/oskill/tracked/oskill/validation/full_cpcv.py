"""Full Combinatorial Purged Cross-Validation (López de Prado 2018, Ch.12)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def full_combinatorial_purged_cv(
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    estimator: Any,
    *,
    n_test_splits: int = 10,
    n_paths: int = 50,
    embargo_pct: float = 0.02,
    test_window_size: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Full Combinatorial Purged Cross-Validation (CPCV).

    Generates multiple paths through the data by randomly selecting consecutive
    test groups, training on purged/embargoed complement, and aggregating scores.

    Algorithm (López de Prado 2018, Ch.12):
        1. Split T obs into n_test_splits equal groups
        2. For each path (up to n_paths):
           a. Randomly choose test_window_size consecutive groups as test
           b. Embargo int(T * embargo_pct) obs after each test boundary
           c. Fit on remaining (train) indices, score on test indices
        3. Aggregate: mean, std, score distribution, haircut (5th pct vs mean)

    Classification detected when len(unique(y)) <= 10 (uses accuracy).
    Otherwise regression (uses R²).

    Args:
        X: Feature matrix of shape (T, P).
        y: Target vector of shape (T,).
        estimator: Object with .fit(X, y) and .predict(X) methods.
        n_test_splits: Number of equal time groups.
        n_paths: Maximum number of random paths to evaluate.
        embargo_pct: Fraction of T to embargo after test boundaries.
        test_window_size: Number of consecutive groups used as test per path.
        seed: Random seed for reproducibility.

    Returns:
        mean_score: float
        score_distribution: np.ndarray
        std_score: float
        p_values: dict {"osr2_positive": float}
        haircut_estimate: float
        n_paths_run: int
        embargo_periods: int

    Reference:
        López de Prado (2018), Ch.12.
    """
    if isinstance(X, pd.DataFrame):
        X_arr = X.values
    else:
        X_arr = np.asarray(X)

    if isinstance(y, pd.Series):
        y_arr = y.values
    else:
        y_arr = np.asarray(y)

    T = len(X_arr)
    rng = np.random.default_rng(seed)

    embargo_periods = max(1, int(T * embargo_pct))

    if test_window_size is None:
        test_window_size = max(1, n_test_splits // 5)
    test_window_size = min(test_window_size, n_test_splits - 1)

    group_size = T // n_test_splits
    group_boundaries = [
        (i * group_size, (i + 1) * group_size if i < n_test_splits - 1 else T)
        for i in range(n_test_splits)
    ]

    is_classification = len(np.unique(y_arr)) <= 10

    def _score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        if is_classification:
            return float(np.mean(y_true == y_pred))
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        if ss_tot < 1e-12:
            return 0.0
        return float(1.0 - ss_res / ss_tot)

    max_start = n_test_splits - test_window_size
    if max_start < 0:
        max_start = 0

    scores: list[float] = []

    for _ in range(n_paths):
        start_grp = int(rng.integers(0, max_start + 1))
        test_grps = list(range(start_grp, start_grp + test_window_size))

        test_start = group_boundaries[test_grps[0]][0]
        test_end = group_boundaries[test_grps[-1]][1]

        embargo_end = min(T, test_end + embargo_periods)

        train_mask = np.ones(T, dtype=bool)
        train_mask[test_start:embargo_end] = False

        train_idx = np.where(train_mask)[0]
        test_idx = np.arange(test_start, test_end)

        if len(train_idx) < 10 or len(test_idx) == 0:
            continue

        try:
            estimator.fit(X_arr[train_idx], y_arr[train_idx])
            y_pred = estimator.predict(X_arr[test_idx])
            s = _score(y_arr[test_idx], y_pred)
            scores.append(s)
        except Exception:
            continue

    if not scores:
        scores = [0.0]

    scores_arr = np.array(scores)
    mean_s = float(np.mean(scores_arr))
    std_s = float(np.std(scores_arr, ddof=1)) if len(scores_arr) > 1 else 0.0
    pct5 = float(np.percentile(scores_arr, 5))
    haircut = float(pct5 - mean_s) if mean_s != 0.0 else 0.0

    return {
        "mean_score": mean_s,
        "score_distribution": scores_arr,
        "std_score": std_s,
        "p_values": {"osr2_positive": float(np.mean(scores_arr > 0))},
        "haircut_estimate": haircut,
        "n_paths_run": len(scores_arr),
        "embargo_periods": embargo_periods,
    }
