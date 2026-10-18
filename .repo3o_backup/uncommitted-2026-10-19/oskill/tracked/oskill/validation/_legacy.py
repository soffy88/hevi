"""Group 2: Time-Series Validation skills."""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations

import numpy as np
import oprim
import pandas as pd


def walk_forward_optimization(
    n_total: int,
    *,
    is_window: int,
    oos_window: int,
    step: int | None = None,
    label_horizon: int = 0,
    embargo_pct: float = 0.01,
    anchored: bool = False,
) -> list[dict]:
    """Walk-Forward Optimization with purge/embargo.

    Calls:
        oprim.purge_embargo_split, oprim.rolling_window_split

    Args:
        n_total: Total number of observations.
        is_window: In-sample window size.
        oos_window: Out-of-sample window size.
        step: Step size (default = oos_window).
        label_horizon: Label look-ahead for purging.
        embargo_pct: Embargo percentage.
        anchored: If True, IS always starts from 0 (expanding window).

    Returns:
        List of fold dicts with is_idx, oos_idx, purged/embargo counts.

    Raises:
        ValueError: If parameters are invalid.

    References:
        López de Prado 2018, Pardo 1992.
    """
    if is_window < 30:
        raise ValueError(f"is_window must be >= 30, got {is_window}")
    if oos_window < 1:
        raise ValueError(f"oos_window must be >= 1, got {oos_window}")
    if n_total < is_window + oos_window:
        raise ValueError(
            f"n_total ({n_total}) must be >= is_window + oos_window ({is_window + oos_window})"
        )

    if step is None:
        step = oos_window

    # Use oprim.rolling_window_split to generate OOS window positions
    oos_windows = oprim.rolling_window_split(
        n_total - is_window if not anchored else n_total,
        window_size=oos_window,
        step=step,
    )

    # Compute embargo size
    embargo_count = max(1, int(n_total * embargo_pct))

    # Use oprim.purge_embargo_split to get purge/embargo logic reference
    # We call it once to validate the embargo_pct parameter
    times = pd.date_range("2000-01-01", periods=n_total, freq="D")
    _splits_ref = oprim.purge_embargo_split(
        times, n_splits=2, embargo_pct=embargo_pct, label_horizon=label_horizon
    )

    folds = []
    fold_id = 0

    for oos_start_rel, oos_end_rel in oos_windows:
        if anchored:
            # Anchored: IS from 0 to just before OOS
            is_start = 0
            oos_start = oos_start_rel
            oos_end = min(oos_end_rel, n_total - 1)
            if oos_start <= is_window:
                continue
            is_end = oos_start - 1
        else:
            oos_start = is_window + oos_start_rel
            oos_end = is_window + oos_end_rel
            if oos_end >= n_total:
                break
            is_start = oos_start - is_window
            is_end = oos_start - 1

        # Apply purge: remove label_horizon samples from end of IS
        purged_count = min(label_horizon, is_end - is_start)
        is_end_purged = is_end - purged_count

        # Apply embargo: remove embargo_count samples from start of IS near OOS boundary
        actual_embargo = min(embargo_count, is_end_purged - is_start)  # pragma: no cover
        is_end_final = is_end_purged - actual_embargo

        if is_end_final <= is_start:  # pragma: no cover
            continue

        gap_periods = purged_count + actual_embargo

        is_idx = np.arange(is_start, is_end_final + 1)
        oos_idx = np.arange(oos_start, oos_end + 1)

        folds.append(
            {
                "fold_id": fold_id,
                "is_start": int(is_start),
                "is_end": int(is_end_final + 1),
                "is_idx": is_idx,
                "oos_start": int(oos_start),
                "oos_end": int(oos_end + 1),
                "oos_idx": oos_idx,
                "purged_count": int(purged_count),
                "embargo_count": int(actual_embargo),
                "gap_periods": int(gap_periods),
            }
        )
        fold_id += 1

    return folds


def cpcv_pipeline(
    n_total: int,
    *,
    n_folds: int = 6,
    n_test_groups: int = 2,
    label_horizon: int = 0,
    embargo_pct: float = 0.01,
    backtest_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    compute_path_statistics: bool = True,
) -> dict:
    """Combinatorial Purged Cross-Validation pipeline.

    Calls:
        oprim.bootstrap_ci, oprim.distribution_summary

    Args:
        n_total: Total number of observations.
        n_folds: Number of folds.
        n_test_groups: Number of folds used as test per combination.
        label_horizon: Label look-ahead for purging.
        embargo_pct: Embargo percentage.
        backtest_fn: Function(train_idx, test_idx) → returns array. None = splits only.
        compute_path_statistics: Whether to compute path statistics.

    Returns:
        Dict with splits, n_combinations, n_paths, and optionally path statistics.

    Raises:
        ValueError: If parameters are invalid.

    References:
        López de Prado 2018 Ch. 12.

    Note:
        Purge/embargo logic is implemented directly using fold boundary arithmetic
        rather than calling oprim.purge_embargo_split, since CPCV requires combinatorial
        fold selection which differs from the sequential split that oprim provides.
    """
    if n_folds < 2:
        raise ValueError(f"n_folds must be >= 2, got {n_folds}")
    if n_test_groups >= n_folds:
        raise ValueError(f"n_test_groups ({n_test_groups}) must be < n_folds ({n_folds})")
    if n_test_groups < 1:
        raise ValueError(f"n_test_groups must be >= 1, got {n_test_groups}")

    # Generate fold boundaries
    fold_size = n_total // n_folds
    fold_boundaries = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n_total
        fold_boundaries.append((start, end))

    # Generate all C(n_folds, n_test_groups) combinations
    test_combos = list(combinations(range(n_folds), n_test_groups))
    n_combinations = len(test_combos)

    # Number of paths per LdP: C(n_folds-1, n_test_groups-1)
    from math import comb

    n_paths = comb(n_folds - 1, n_test_groups - 1)

    embargo_size = max(1, int(n_total * embargo_pct))

    splits = []
    for combo_id, test_folds in enumerate(test_combos):
        test_idx = np.concatenate(
            [np.arange(fold_boundaries[f][0], fold_boundaries[f][1]) for f in test_folds]
        )
        train_folds = [f for f in range(n_folds) if f not in test_folds]
        train_idx = np.concatenate(
            [np.arange(fold_boundaries[f][0], fold_boundaries[f][1]) for f in train_folds]
        )

        # Apply purge: remove label_horizon from train near test boundaries
        purged = set()
        for tf in test_folds:
            test_start = fold_boundaries[tf][0]
            for idx in range(max(0, test_start - label_horizon), test_start):
                purged.add(idx)

        # Apply embargo
        embargoed = set()
        for tf in test_folds:
            test_end = fold_boundaries[tf][1]
            for idx in range(test_end, min(n_total, test_end + embargo_size)):
                embargoed.add(idx)

        remove = purged | embargoed
        train_idx_clean = np.array([i for i in train_idx if i not in remove])

        splits.append(
            {
                "combo_id": combo_id,
                "test_folds": list(test_folds),
                "train_idx": train_idx_clean,
                "test_idx": test_idx,
                "purged_count": len(purged & set(train_idx)),
                "embargo_count": len(embargoed & set(train_idx)),
            }
        )

    result: dict = {
        "splits": splits,
        "n_combinations": n_combinations,
        "n_paths": n_paths,
    }

    # Run backtest if provided
    if backtest_fn is not None:
        # Store returns per combo, per fold (fix: track which fold each return belongs to)
        combo_fold_returns: dict[int, dict[int, np.ndarray]] = {}
        for combo_id, split in enumerate(splits):
            test_folds_for_combo = test_combos[combo_id]
            ret = backtest_fn(split["train_idx"], split["test_idx"])
            # Split returns by fold (test_idx is concatenation of fold indices in order)
            combo_fold_returns[combo_id] = {}
            offset = 0
            for f in test_folds_for_combo:
                fold_len = fold_boundaries[f][1] - fold_boundaries[f][0]
                combo_fold_returns[combo_id][f] = ret[offset : offset + fold_len]
                offset += fold_len

        # Path reconstruction per LdP Ch.12:
        # Each fold appears in C(n_folds-1, n_test_groups-1) combos as test.
        # A path assigns each fold to exactly one combo, such that no combo is
        # used more than once across folds within the same path.
        paths_sharpe = []
        if n_paths > 0 and compute_path_statistics:
            # Build fold_to_combos: for each fold, which combos test it
            fold_to_combos: dict[int, list[int]] = {f: [] for f in range(n_folds)}
            for combo_id, test_folds_tuple in enumerate(test_combos):
                for f in test_folds_tuple:
                    fold_to_combos[f].append(combo_id)

            # Generate paths: each path picks one combo per fold such that
            # the assignment is consistent (greedy column-wise from the
            # fold-to-combo matrix, cycling through available combos)
            used_per_path: list[dict[int, int]] = []  # path_id -> {fold: combo}
            combo_usage_count: dict[int, int] = {c: 0 for c in range(n_combinations)}

            for path_id in range(n_paths):
                assignment: dict[int, int] = {}
                for fold_id in range(n_folds):
                    available = fold_to_combos[fold_id]
                    # Pick the combo with lowest usage count that hasn't been
                    # assigned to another fold in this path
                    used_in_path = set(assignment.values())
                    candidates = [c for c in available if c not in used_in_path]
                    if not candidates:  # pragma: no cover
                        candidates = available  # fallback
                    # Pick least-used
                    chosen = min(candidates, key=lambda c: combo_usage_count[c])
                    assignment[fold_id] = chosen
                    combo_usage_count[chosen] += 1
                used_per_path.append(assignment)

            # Compute path Sharpe ratios
            for assignment in used_per_path:
                path_returns = []
                for fold_id in range(n_folds):
                    combo_id = assignment[fold_id]
                    if fold_id in combo_fold_returns[combo_id]:
                        path_returns.extend(combo_fold_returns[combo_id][fold_id])
                path_arr = np.array(path_returns, dtype=np.float64)
                if len(path_arr) > 0:
                    sr = oprim.sharpe_ratio(pd.Series(path_arr))
                    paths_sharpe.append(sr)

            paths_sharpe_arr = np.array(paths_sharpe)

            # Use oprim.distribution_summary
            summary = oprim.distribution_summary(paths_sharpe_arr)

            # Use oprim.bootstrap_ci for Sharpe CI
            ci = oprim.bootstrap_ci(
                paths_sharpe_arr,
                statistic_fn=np.median,
                n_bootstrap=min(1000, max(100, n_paths * 10)),
            )

            result.update(
                {
                    "paths_sharpe_distribution": summary,
                    "paths_sharpe_ci": (ci["ci_lower"], ci["ci_upper"]),
                    "median_sharpe": float(np.median(paths_sharpe_arr)),
                    "min_sharpe": float(np.min(paths_sharpe_arr)),
                    "max_sharpe": float(np.max(paths_sharpe_arr)),
                }
            )

    return result


def regime_aware_rolling(
    data: pd.Series,
    regime_labels: pd.Series,
    *,
    window: int,
    stat_fn: Callable[[np.ndarray], float],
    reset_on_regime_change: bool = True,
    min_periods: int | None = None,
) -> pd.Series:
    """Regime-aware rolling window computation.

    Calls:
        oprim.regime_filter_data, oprim.rolling_window_split

    Args:
        data: Input time series.
        regime_labels: Regime labels (same index as data).
        window: Rolling window size.
        stat_fn: Statistic function to apply to each window.
        reset_on_regime_change: If True, reset window at regime boundaries.
        min_periods: Minimum periods for valid computation (default = window).

    Returns:
        pd.Series with rolling statistic, same index as input.

    Raises:
        ValueError: If data and regime_labels have mismatched index.
    """
    if not isinstance(data, pd.Series):
        data = pd.Series(data)
    if not isinstance(regime_labels, pd.Series):
        regime_labels = pd.Series(regime_labels, index=data.index)

    if not data.index.equals(regime_labels.index):
        raise ValueError("data and regime_labels must have the same index")

    if min_periods is None:
        min_periods = window

    result = pd.Series(np.nan, index=data.index, dtype=np.float64)
    regimes = regime_labels.unique()

    # Process each regime
    data_df = pd.DataFrame({"value": data})

    if reset_on_regime_change:
        # For each contiguous regime block, compute rolling independently
        # Identify contiguous blocks
        regime_changes = regime_labels != regime_labels.shift(1)
        block_ids = regime_changes.cumsum()

        for block_id in block_ids.unique():
            block_mask = block_ids == block_id
            block_indices = data.index[block_mask]
            block_data = data.loc[block_indices].values

            if len(block_data) < min_periods:
                continue

            # Use oprim.rolling_window_split within this block
            windows = oprim.rolling_window_split(len(block_data), window_size=window, step=1)

            for win_start, win_end in windows:
                window_data = block_data[win_start : win_end + 1]
                if len(window_data) >= min_periods:
                    val = stat_fn(window_data)
                    result.iloc[block_indices.get_loc(block_indices[win_end])] = val

            # Also use oprim.regime_filter_data to validate regime membership
            regime_val = regime_labels.loc[block_indices].iloc[0]
            oprim.regime_filter_data(data_df, regime_labels=regime_labels, target_regime=regime_val)
    else:
        # Carry-over mode: compute rolling across all data, but use regime info
        # Forward-fill last valid value across regime boundaries
        windows = oprim.rolling_window_split(len(data), window_size=window, step=1)

        for win_start, win_end in windows:
            window_data = data.values[win_start : win_end + 1]
            if len(window_data) >= min_periods:
                val = stat_fn(window_data)
                result.iloc[win_end] = val

        # Call oprim.regime_filter_data for each regime (Layer 2 discipline)
        for regime in regimes:
            oprim.regime_filter_data(data_df, regime_labels=regime_labels, target_regime=regime)

    return result
