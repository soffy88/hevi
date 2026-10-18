"""Group 5: Prediction Quality skills."""

from __future__ import annotations

from typing import Literal

import numpy as np
import oprim
import pandas as pd


def calibration_analysis(
    predictions: np.ndarray,
    outcomes: np.ndarray,
    *,
    n_bins: int = 10,
    binning: Literal["equal_width", "equal_freq"] = "equal_width",
    include_reliability_diagram: bool = True,
    include_bayesian_ci: bool = True,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> dict:
    """Full calibration analysis with Brier decomposition, ECE, MCE.

    Calls:
        oprim.brier_score_decomposed, oprim.percentile_rank, oprim.bayes_beta_update

    Args:
        predictions: Predicted probabilities in [0, 1].
        outcomes: Binary outcomes (0 or 1).
        n_bins: Number of bins for calibration.
        binning: Binning strategy ('equal_width' or 'equal_freq').
        include_reliability_diagram: Whether to compute reliability diagram.
        include_bayesian_ci: Whether to compute Bayesian CI per bin.
        prior_alpha: Beta prior alpha.
        prior_beta: Beta prior beta.

    Returns:
        Dict with brier_score, reliability, resolution, uncertainty, skill_score,
        ece, mce, reliability_diagram, n_obs.

    Raises:
        ValueError: If inputs are invalid.

    References:
        Murphy 1973, Naeini-Cooper-Hauskrecht 2015.
    """
    predictions = np.asarray(predictions, dtype=np.float64)
    outcomes = np.asarray(outcomes, dtype=np.float64)

    if len(predictions) != len(outcomes):
        raise ValueError(
            f"predictions and outcomes must have same length: {len(predictions)} != {len(outcomes)}"
        )
    if len(predictions) == 0:
        raise ValueError("predictions must not be empty")
    if np.any(predictions < 0) or np.any(predictions > 1):
        raise ValueError("predictions must be in [0, 1]")
    if not np.all(np.isin(outcomes, [0, 1])):
        raise ValueError("outcomes must be binary (0 or 1)")

    N = len(predictions)

    # Use oprim.brier_score_decomposed
    brier_result = oprim.brier_score_decomposed(predictions, outcomes=outcomes, n_bins=n_bins)

    # Compute bin assignments
    if binning == "equal_width":
        bin_edges = np.linspace(0, 1, n_bins + 1)
        bin_indices = np.digitize(predictions, bin_edges[1:-1])
    else:
        # Equal frequency: use oprim.percentile_rank to help
        pred_series = pd.Series(predictions)
        ranks = oprim.percentile_rank(pred_series, method="expanding")
        # Create equal-frequency bins
        bin_edges = np.linspace(0, 1, n_bins + 1)
        rank_values = ranks.values
        bin_indices = np.digitize(rank_values, bin_edges[1:-1])

    # Compute ECE and MCE
    ece = 0.0
    mce = 0.0
    diagram_rows = []

    for b in range(n_bins):
        mask = bin_indices == b
        n_bin = mask.sum()
        if n_bin == 0:
            continue

        avg_pred = predictions[mask].mean()
        avg_outcome = outcomes[mask].mean()
        gap = abs(avg_pred - avg_outcome)

        ece += (n_bin / N) * gap
        mce = max(mce, gap)

        if include_reliability_diagram:
            row = {
                "bin_id": b,
                "bin_min": bin_edges[b] if binning == "equal_width" else b / n_bins,
                "bin_max": bin_edges[b + 1] if binning == "equal_width" else (b + 1) / n_bins,
                "n": int(n_bin),
                "avg_prediction": float(avg_pred),
                "avg_outcome": float(avg_outcome),
            }

            if include_bayesian_ci:
                successes = int(outcomes[mask].sum())
                failures = n_bin - successes
                posterior = oprim.bayes_beta_update(
                    prior_alpha,
                    prior_beta=prior_beta,
                    successes=successes,
                    failures=failures,
                    posterior_quantiles=[0.025, 0.975],
                )
                row["ci_low"] = posterior.get("q_0.025", posterior.get("q_0.05", 0.0))
                row["ci_high"] = posterior.get("q_0.975", posterior.get("q_0.95", 1.0))
            else:
                row["ci_low"] = None
                row["ci_high"] = None

            diagram_rows.append(row)

    # Build reliability diagram DataFrame
    reliability_diagram = None
    if include_reliability_diagram and diagram_rows:
        reliability_diagram = pd.DataFrame(diagram_rows)

    # Skill score: 1 - BS/uncertainty
    uncertainty = brier_result.get("uncertainty", 0.25)
    skill_score = brier_result.get("skill", 0.0)

    return {
        "brier_score": float(brier_result["brier_score"]),
        "reliability": float(brier_result["reliability"]),
        "resolution": float(brier_result["resolution"]),
        "uncertainty": float(uncertainty),
        "skill_score": float(skill_score),
        "ece": float(ece),
        "mce": float(mce),
        "n_bins": n_bins,
        "binning": binning,
        "reliability_diagram": reliability_diagram,
        "n_obs": N,
    }
