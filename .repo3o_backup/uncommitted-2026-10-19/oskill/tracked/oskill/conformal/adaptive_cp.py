"""Adaptive Conformal Inference (Gibbs & Candès 2021)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def adaptive_conformal_inference(
    predictions: np.ndarray | pd.Series,
    actuals: np.ndarray | pd.Series,
    *,
    alpha_target: float = 0.10,
    gamma: float = 0.005,
    initial_alpha: float | None = None,
    score_function: Literal["absolute", "signed"] = "absolute",
) -> dict[str, np.ndarray]:
    """Adaptive Conformal Inference (Gibbs & Candès 2021).

    Online algorithm that adapts the miscoverage level alpha_t over time to
    achieve long-run marginal coverage equal to 1 - alpha_target, even under
    distribution shift.

    Parameters
    ----------
    predictions : np.ndarray or pd.Series
        Sequence of model predictions.
    actuals : np.ndarray or pd.Series
        Sequence of true values (same length as predictions).
    alpha_target : float
        Target miscoverage level. Default 0.10 → target 90% coverage.
    gamma : float
        Step size for alpha adaptation. Default 0.005.
    initial_alpha : float or None
        Starting value for alpha. Defaults to alpha_target.
    score_function : {"absolute", "signed"}
        Nonconformity score type.

    Returns
    -------
    dict with keys:
        lower, upper : np.ndarray — per-time-step interval bounds
        alphas : np.ndarray — adaptive alpha sequence
        empirical_coverage_running : np.ndarray — running fraction covered
        final_alpha : float — alpha value at the last time step
        long_run_coverage : float — empirical coverage over last 100 points
        adaptation_rate : float — gamma used

    References
    ----------
    .. [1] Gibbs, I. & Candès, E. (2021). Adaptive Conformal Inference Under
           Distribution Shift. NeurIPS 2021.
    """
    preds = np.asarray(predictions, dtype=np.float64)
    acts = np.asarray(actuals, dtype=np.float64)

    if len(preds) != len(acts):
        raise ValueError(
            f"predictions and actuals must have the same length, got {len(preds)} vs {len(acts)}"
        )
    if not (0 < alpha_target < 1):
        raise ValueError(f"alpha_target must be in (0, 1), got {alpha_target}")

    T = len(preds)
    alpha_t = float(initial_alpha) if initial_alpha is not None else float(alpha_target)
    alpha_t = float(np.clip(alpha_t, 0.001, 0.999))

    alphas = np.zeros(T)
    lower = np.zeros(T)
    upper = np.zeros(T)
    covered = np.zeros(T, dtype=bool)

    scores_so_far: list[float] = []

    for t in range(T):
        alphas[t] = alpha_t

        # Build interval using quantile of scores_so_far
        if len(scores_so_far) == 0:
            q_t = 0.0
        else:
            arr = np.array(scores_so_far)
            n_s = len(arr)
            level = float(np.minimum(np.ceil((n_s + 1) * (1 - alpha_t)) / n_s, 1.0))
            q_t = float(np.quantile(arr, level, method="higher"))
            if score_function == "absolute":
                q_t = max(0.0, q_t)
            else:
                q_t = abs(q_t)

        lower[t] = preds[t] - q_t
        upper[t] = preds[t] + q_t

        # Observe actual and compute score
        if score_function == "absolute":
            score_t = float(abs(acts[t] - preds[t]))
        else:
            score_t = float(acts[t] - preds[t])

        scores_so_far.append(score_t)

        # Check coverage
        covered[t] = bool(lower[t] <= acts[t] <= upper[t])

        # Compute error indicator: 1 if NOT covered
        err_t = 0.0 if covered[t] else 1.0

        # Update alpha
        alpha_t = float(np.clip(alpha_t + gamma * (alpha_target - err_t), 0.001, 0.999))

    # Compute running coverage
    empirical_coverage_running = np.cumsum(covered.astype(float)) / np.arange(1, T + 1)

    # Long-run coverage: last 100 points
    tail = min(100, T)
    long_run_coverage = float(np.mean(covered[-tail:]))

    return {
        "lower": lower,
        "upper": upper,
        "alphas": alphas,
        "empirical_coverage_running": empirical_coverage_running,
        "final_alpha": float(alpha_t),
        "long_run_coverage": long_run_coverage,
        "adaptation_rate": gamma,
    }
