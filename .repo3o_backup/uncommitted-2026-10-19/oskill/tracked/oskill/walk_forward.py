"""oskill.walk_forward — Walk-forward backtest with CPCV splits and DSR.

Composites:
    - oprim.cpcv_split       (purged cross-validation fold generation)
    - oprim.deflated_sharpe  (multiple-testing-adjusted performance metric)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def walk_forward(
    strategy_fn: Callable[[list, list], dict[str, Any]],
    data: Any,
    *,
    n_splits: int = 5,
    embargo: int = 0,
    n_trials: int | None = None,
    periods: int = 252,
) -> dict[str, Any]:
    """Run a walk-forward backtest using CPCV splits and Deflated Sharpe Ratio.

    Composites used:
        1. oprim.cpcv_split      — generates purged train/test folds.
        2. oprim.deflated_sharpe — adjusts OOS Sharpe for multiple-testing
           bias across all evaluated splits.

    *strategy_fn* must accept ``(train_data, test_data)`` and return a dict
    with at least ``sharpe`` (float) and optionally ``returns`` (list[float]).

    Args:
        strategy_fn: Callable ``(train_data, test_data) -> dict``.
            Must return ``{"sharpe": float, ...}``.
        data: Full dataset (list, array, or pandas Series/DataFrame).
        n_splits: Number of CPCV folds (≥ 2).
        embargo: Observations to drop at train/test boundaries.
        n_trials: Total strategies evaluated (used for DSR; defaults to
            *n_splits* when None).
        periods: Annualisation factor for Sharpe (252 = daily).

    Returns:
        Dict with keys:

        - ``fold_results``      – List of per-fold dicts (fold, sharpe, …).
        - ``oos_sharpes``       – List of OOS Sharpe ratios per fold.
        - ``mean_oos_sharpe``   – Mean OOS Sharpe across folds.
        - ``deflated_sharpe``   – DSR-adjusted metric (dict from deflated_sharpe).
        - ``n_splits``          – Number of folds.
    """
    from oprim.cpcv_split import cpcv_split  # noqa: PLC0415
    from oprim.deflated_sharpe import deflated_sharpe  # noqa: PLC0415

    splits = cpcv_split(data, n_splits=n_splits, embargo=embargo)

    fold_results: list[dict[str, Any]] = []
    oos_sharpes: list[float] = []

    for split in splits:
        train_idx = split["train_idx"]
        test_idx = split["test_idx"]

        if hasattr(data, "iloc"):
            train_data = data.iloc[train_idx]
            test_data = data.iloc[test_idx]
        else:
            train_data = [data[i] for i in train_idx]
            test_data = [data[i] for i in test_idx]

        result = strategy_fn(train_data, test_data)
        sharpe = float(result.get("sharpe", 0.0))
        oos_sharpes.append(sharpe)
        fold_results.append({"fold": split["fold"], "sharpe": sharpe, **result})

    mean_sr = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0.0
    all_returns = [r for fr in fold_results for r in fr.get("returns", [])]
    n_trials_used = n_trials if n_trials is not None else n_splits

    dsr = deflated_sharpe(
        mean_sr,
        n_trials=max(1, n_trials_used),
        returns=all_returns or None,
        periods=periods,
    )

    return {
        "fold_results": fold_results,
        "oos_sharpes": oos_sharpes,
        "mean_oos_sharpe": mean_sr,
        "deflated_sharpe": dsr,
        "n_splits": n_splits,
    }
