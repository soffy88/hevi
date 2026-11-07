"""Embargo Purged Cross-Validation (López de Prado 2018, Ch.7.2-7.3)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def embargo_purged_cv(
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    barrier_times: pd.DataFrame | None,
    *,
    n_splits: int = 5,
    embargo_pct: float = 0.01,
    purge_pct: float = 0.0,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Embargo Purged Cross-Validation.

    Builds K-fold splits where the training set has been purged of any
    observations whose end time overlaps with the test window, and embargoed
    for embargo_pct*T rows immediately following the test window — preventing
    information leakage from future observations.

    When barrier_times is None or X has a non-DatetimeIndex, integer-index
    fallback mode is used: each row is treated as a point event, and purge/
    embargo are applied as integer offsets.

    Algorithm (López de Prado 2018, Ch.7.2):
        1. Split T obs into n_splits equal folds
        2. For each fold k as test:
           a. test_indices = fold k rows
           b. purge_periods = int(T * purge_pct)
           c. embargo_periods = max(1, int(T * embargo_pct))
           d. Remove rows in [test_start - purge_periods, test_end + embargo_periods)
              from the training set
        3. Return list of (train_idx, test_idx) as integer arrays

    Args:
        X: Feature matrix of shape (T, P).
        y: Target vector of shape (T,).
        barrier_times: DataFrame with DatetimeIndex and 'end' column.
                       If None, integer-index mode is used.
        n_splits: Number of cross-validation folds.
        embargo_pct: Fraction of T to remove after each test fold.
        purge_pct: Fraction of T to remove before each test fold.

    Returns:
        List of (train_indices, test_indices) tuples with integer np.ndarray.

    Reference:
        López de Prado (2018), Ch.7.2.
    """
    if isinstance(X, pd.DataFrame):
        T = len(X)
        use_datetime = isinstance(X.index, pd.DatetimeIndex) and barrier_times is not None
    else:
        T = len(X)
        use_datetime = False

    fold_size = T // n_splits
    folds: list[tuple[int, int]] = []
    for i in range(n_splits):
        start = i * fold_size
        end = start + fold_size if i < n_splits - 1 else T
        folds.append((start, end))

    embargo_periods = max(1, int(T * embargo_pct))
    purge_periods = int(T * purge_pct)

    splits: list[tuple[np.ndarray, np.ndarray]] = []

    if use_datetime and barrier_times is not None:
        df_bt = barrier_times

        for fold_start, fold_end in folds:
            test_idx = np.arange(fold_start, fold_end)
            if isinstance(X, pd.DataFrame):
                test_times = X.index[test_idx]
            else:
                test_times = pd.RangeIndex(fold_start, fold_end)

            t0 = test_times[0]
            t1 = test_times[-1]

            # Purge: events whose barrier end falls within test window
            in_purge = (df_bt.index >= t0) & (df_bt["end"] <= t1)
            # Embargo: events starting just after test window
            embargo_cutoff = t1 + pd.Timedelta(embargo_periods, unit="D")
            in_embargo = (df_bt.index > t1) & (df_bt.index <= embargo_cutoff)

            excluded = set(np.where(in_purge | in_embargo)[0].tolist())
            excluded.update(test_idx.tolist())

            train_idx = np.array([i for i in range(T) if i not in excluded], dtype=np.intp)
            splits.append((train_idx, test_idx))

    else:
        for fold_start, fold_end in folds:
            test_idx = np.arange(fold_start, fold_end)
            excl_start = max(0, fold_start - purge_periods)
            excl_end = min(T, fold_end + embargo_periods)
            train_idx = np.concatenate(
                [
                    np.arange(0, excl_start),
                    np.arange(excl_end, T),
                ]
            ).astype(np.intp)
            splits.append((train_idx, test_idx))

    return splits
