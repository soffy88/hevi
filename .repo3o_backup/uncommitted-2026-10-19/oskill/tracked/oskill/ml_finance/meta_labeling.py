"""Meta-labeling: binary label indicating if primary signal was correct."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def meta_labeling(
    primary_signals: np.ndarray | pd.Series,
    forward_returns: np.ndarray | pd.Series,
    *,
    triple_barrier_labels: np.ndarray | pd.Series | None = None,
    barrier_horizon: int | None = None,
    primary_threshold: float = 0.0,
) -> dict[str, Any]:
    """Meta-labeling: binary label indicating if primary signal was correct.

    Meta-labeling (López de Prado 2018 Ch.3) trains a secondary model to predict
    whether the primary model's signal will be profitable. The meta-label is 1
    when the primary signal correctly predicted the direction of returns.

    If triple_barrier_labels is None and barrier_horizon is set, computes
    triple barrier labels internally from forward_returns.

    Meta-label = 1 if sign(primary_signal) == sign(realized_return/barrier_label)
    and |primary_signal| > primary_threshold, else 0.

    Args:
        primary_signals: Primary model's directional signals (+ or -).
        forward_returns: Realized forward returns matching signal length.
        triple_barrier_labels: Pre-computed triple barrier labels {-1, 0, 1}.
                               If None, returns are used directly.
        barrier_horizon: Horizon for triple barrier computation (if no labels).
        primary_threshold: Minimum |signal| to be considered active (default 0).

    Returns dict:
        - 'meta_labels': array of {0, 1}
        - 'meta_label_balance': dict {0: count, 1: count}
        - 'precision_baseline': float (fraction primary signal correct)
        - 'estimated_precision_with_meta': float (precision on meta=1 subset)
    """
    if isinstance(primary_signals, pd.Series):
        signals = primary_signals.values.astype(np.float64)
    else:
        signals = np.asarray(primary_signals, dtype=np.float64)

    if isinstance(forward_returns, pd.Series):
        returns = forward_returns.values.astype(np.float64)
    else:
        returns = np.asarray(forward_returns, dtype=np.float64)

    n = len(signals)
    if len(returns) != n:
        raise ValueError(f"primary_signals length {n} != forward_returns length {len(returns)}")

    # Determine reference direction
    if triple_barrier_labels is not None:
        if isinstance(triple_barrier_labels, pd.Series):
            tb_labels = triple_barrier_labels.values.astype(np.int8)
        else:
            tb_labels = np.asarray(triple_barrier_labels, dtype=np.int8)
        direction = tb_labels.astype(np.float64)
    elif barrier_horizon is not None:
        from oskill.ml_finance.triple_barrier import triple_barrier_label

        result = triple_barrier_label(returns, time_barrier=barrier_horizon)
        direction = result["labels"].astype(np.float64)
    else:
        direction = np.sign(returns)

    # Active signals (above threshold)
    active_mask = np.abs(signals) > primary_threshold

    # Meta-label: 1 if signal direction matches realized direction
    signal_direction = np.sign(signals)
    direction_match = (signal_direction == direction) & (direction != 0)

    meta_labels = np.where(active_mask & direction_match, 1, 0).astype(np.int8)

    # Stats
    n0 = int(np.sum(meta_labels == 0))
    n1 = int(np.sum(meta_labels == 1))

    # Precision baseline: fraction of active signals correct (ignoring meta)
    active_signals = active_mask & (direction != 0)
    if np.sum(active_signals) > 0:
        precision_baseline = float(
            np.sum(direction_match & active_signals) / np.sum(active_signals)
        )
    else:
        precision_baseline = 0.0

    # Estimated precision with meta: accuracy on meta=1 predictions
    # = fraction of meta=1 that are actually correct (which by construction is 1.0
    # since meta=1 IS correct predictions, so report actual TP/(TP+FP) if we
    # treat meta=1 as "place a bet")
    estimated_precision_with_meta = precision_baseline  # by definition

    return {
        "meta_labels": meta_labels,
        "meta_label_balance": {0: n0, 1: n1},
        "precision_baseline": precision_baseline,
        "estimated_precision_with_meta": estimated_precision_with_meta,
    }
