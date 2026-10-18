"""Split Conformal Prediction Interval (Papadopoulos et al. 2002, Vovk et al. 2005)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import oprim
import pandas as pd


def conformal_prediction_interval(
    calibration_predictions: np.ndarray | pd.Series,
    calibration_actuals: np.ndarray | pd.Series,
    test_predictions: np.ndarray | pd.Series,
    *,
    alpha: float = 0.10,
    score_function: Literal["absolute", "signed", "normalized"] = "absolute",
    score_normalizer: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Split Conformal Prediction Interval.

    Computes prediction intervals using the split conformal prediction method.
    Uses calibration set nonconformity scores to find the (1-alpha) quantile,
    then applies it to construct intervals for test predictions.

    Parameters
    ----------
    calibration_predictions : np.ndarray or pd.Series
        Model predictions on the calibration set.
    calibration_actuals : np.ndarray or pd.Series
        True labels for the calibration set.
    test_predictions : np.ndarray or pd.Series
        Model predictions for the test set.
    alpha : float
        Miscoverage level in (0, 1). Default 0.10 targets 90% coverage.
    score_function : {"absolute", "signed", "normalized"}
        Nonconformity score type.
    score_normalizer : np.ndarray or None
        Per-sample normalizer for "normalized" score (e.g., predicted std).
        Must match length of calibration set.

    Returns
    -------
    dict with keys:
        lower, upper : np.ndarray — interval bounds for test set
        point_predictions : np.ndarray — test predictions
        quantile_used : float — q used to build intervals
        alpha : float — miscoverage level
        expected_coverage : float — 1 - alpha
        fingerprint : str — SHA-256 hash of config

    References
    ----------
    .. [1] Vovk, V., Gammerman, A., & Shafer, G. (2005). Algorithmic Learning in
           a Random World. Springer.
    .. [2] Papadopoulos, H. et al. (2002). Inductive Confidence Machines for
           Regression. ECML.
    """
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if score_function not in ("absolute", "signed", "normalized"):
        raise ValueError(
            f"score_function must be 'absolute', 'signed', or 'normalized', got {score_function!r}"
        )

    cal_pred = np.asarray(calibration_predictions, dtype=np.float64)
    cal_act = np.asarray(calibration_actuals, dtype=np.float64)
    test_pred = np.asarray(test_predictions, dtype=np.float64)

    n = len(cal_pred)
    if len(cal_act) != n:
        raise ValueError(
            f"calibration_predictions and calibration_actuals must have the same length, "
            f"got {n} vs {len(cal_act)}"
        )

    # Compute nonconformity scores
    residuals = cal_act - cal_pred
    if score_function == "absolute":
        scores = np.abs(residuals)
    elif score_function == "signed":
        scores = residuals  # will symmetrize via positive quantile
    else:  # normalized
        if score_normalizer is None:
            raise ValueError("score_normalizer must be provided for 'normalized' score_function")
        norm = np.asarray(score_normalizer, dtype=np.float64)
        if len(norm) != n:
            raise ValueError(
                f"score_normalizer length {len(norm)} does not match calibration length {n}"
            )
        scores = np.abs(residuals) / np.maximum(norm, 1e-10)

    # Compute quantile: ceil((n+1)*(1-alpha))/n
    level = np.minimum(np.ceil((n + 1) * (1 - alpha)) / n, 1.0)
    q = float(np.quantile(scores, level, method="higher"))

    # Clip for absolute/normalized (non-negative scores)
    if score_function in ("absolute", "normalized"):
        max_score = float(np.max(scores)) if len(scores) > 0 else 0.0
        q = float(np.clip(q, 0.0, max_score))
    else:
        # For signed: symmetrize — use absolute value of q
        q = abs(q)

    lower = test_pred - q
    upper = test_pred + q

    fingerprint = oprim.sha256_hash(
        oprim.canonical_json({"alpha": alpha, "cal_len": n, "score_function": score_function})
    )

    return {
        "lower": lower,
        "upper": upper,
        "point_predictions": test_pred,
        "quantile_used": q,
        "alpha": alpha,
        "expected_coverage": 1.0 - alpha,
        "fingerprint": fingerprint,
    }
