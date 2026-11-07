"""Conformal Prediction with Change Point Adaptation."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import oprim
import pandas as pd


def conformal_with_change_points(
    predictions: np.ndarray | pd.Series,
    actuals: np.ndarray | pd.Series,
    *,
    alpha: float = 0.10,
    detection_method: Literal["bocpd", "pelt", "external"] = "bocpd",
    detection_kwargs: dict | None = None,
    change_points: list[int] | None = None,
    min_segment_length: int = 20,
) -> dict[str, Any]:
    """Conformal Prediction with Change Point Adaptation.

    Detects structural breaks in the time series and computes per-segment
    conformal quantiles. Points in short segments fall back to the global
    quantile.

    Parameters
    ----------
    predictions : np.ndarray or pd.Series
        Model predictions (used as calibration and test simultaneously,
        evaluating each point using its segment's historical errors).
    actuals : np.ndarray or pd.Series
        True values.
    alpha : float
        Miscoverage level in (0, 1).
    detection_method : {"bocpd", "pelt", "external"}
        Change point detection method. "external" uses the ``change_points``
        argument directly.
    detection_kwargs : dict or None
        Extra keyword arguments passed to the detection function.
    change_points : list[int] or None
        Change point indices (required if detection_method="external").
    min_segment_length : int
        Minimum number of points in a segment to compute a local quantile.
        Segments shorter than this use the global quantile.

    Returns
    -------
    dict with keys:
        lower, upper : np.ndarray — interval bounds
        change_points : list[int] — detected or provided CPs
        segments : list[tuple[int, int]] — (start, end) index pairs
        per_segment_quantiles : list[float] — quantile per segment
        segment_assignments : np.ndarray — segment index for each point
        fingerprint : str — SHA-256 config hash

    References
    ----------
    .. [1] Barber, R. F. et al. (2023). Conformal prediction beyond exchangeability.
           Annals of Statistics.
    """
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    preds = np.asarray(predictions, dtype=np.float64)
    acts = np.asarray(actuals, dtype=np.float64)
    T = len(preds)

    if len(acts) != T:
        raise ValueError(
            f"predictions and actuals must have the same length, got {T} vs {len(acts)}"
        )

    # --- Detect change points ---
    kwargs = detection_kwargs or {}
    if detection_method == "external":
        if change_points is None:
            cps: list[int] = []
        else:
            cps = sorted(int(cp) for cp in change_points if 0 < cp < T)
    elif detection_method == "bocpd":
        from oskill import bocpd_bayesian

        result_bocpd = bocpd_bayesian(acts, **kwargs)
        cps = sorted(int(cp) for cp in result_bocpd["change_points"] if 0 < cp < T)
    elif detection_method == "pelt":
        from oskill import pelt_change_point

        result_pelt = pelt_change_point(acts, **kwargs)
        cps = sorted(int(cp) for cp in result_pelt["change_points"] if 0 < cp < T)
    else:
        raise ValueError(f"Unknown detection_method: {detection_method!r}")

    # --- Build segments from change points ---
    boundaries = [0] + cps + [T]
    segments: list[tuple[int, int]] = [
        (boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)
    ]

    # --- Compute global quantile as fallback ---
    global_residuals = np.abs(acts - preds)
    n_global = len(global_residuals)
    global_level = float(np.minimum(np.ceil((n_global + 1) * (1 - alpha)) / n_global, 1.0))
    global_q = float(np.quantile(global_residuals, global_level, method="higher"))

    # --- Per-segment quantiles ---
    per_segment_quantiles: list[float] = []
    segment_assignments = np.zeros(T, dtype=int)

    for seg_idx, (start, end) in enumerate(segments):
        segment_assignments[start:end] = seg_idx
        seg_len = end - start
        if seg_len >= min_segment_length:
            seg_preds = preds[start:end]
            seg_acts = acts[start:end]
            seg_resid = np.abs(seg_acts - seg_preds)
            n_seg = len(seg_resid)
            level = float(np.minimum(np.ceil((n_seg + 1) * (1 - alpha)) / n_seg, 1.0))
            q = float(np.quantile(seg_resid, level, method="higher"))
            per_segment_quantiles.append(q)
        else:
            per_segment_quantiles.append(global_q)

    # --- Build intervals ---
    lower = np.zeros(T)
    upper = np.zeros(T)
    for seg_idx, (start, end) in enumerate(segments):
        q = per_segment_quantiles[seg_idx]
        lower[start:end] = preds[start:end] - q
        upper[start:end] = preds[start:end] + q

    fingerprint = oprim.sha256_hash(
        oprim.canonical_json(
            {
                "alpha": alpha,
                "detection_method": detection_method,
                "min_segment_length": min_segment_length,
                "n_change_points": len(cps),
                "T": T,
            }
        )
    )

    return {
        "lower": lower,
        "upper": upper,
        "change_points": cps,
        "segments": segments,
        "per_segment_quantiles": per_segment_quantiles,
        "segment_assignments": segment_assignments,
        "fingerprint": fingerprint,
    }
