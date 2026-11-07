"""Bayesian Online Change Point Detection (Adams & MacKay, 2007)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd


def bocpd_bayesian(
    series: np.ndarray | pd.Series,
    *,
    hazard_rate: float = 0.01,
    model: Literal["gaussian", "studentt"] = "gaussian",
    prior_mean: float = 0.0,
    prior_var: float = 1.0,
    alpha: float = 0.1,
    min_segment_length: int = 5,
) -> dict[str, Any]:
    """Bayesian Online Change Point Detection (Adams & MacKay, 2007).

    Computes posterior run-length distribution P(r_t | x_{1:t}).
    A change point is detected when the maximum a posteriori run length resets
    near zero after being elevated for min_segment_length steps.

    For Gaussian model: Normal-Gamma conjugate prior.
    For StudentT: more robust to outliers (heavier tails).

    Args:
        series: Univariate time series (length T).
        hazard_rate: Prior probability of a change point per time step (default 0.01).
        model: Predictive model — 'gaussian' (Normal-Gamma) or 'studentt'.
        prior_mean: Prior mean for the Normal-Gamma (mu_0).
        prior_var: Prior variance scale (var_0).
        alpha: Significance threshold for change point detection (unused in MAP approach).
        min_segment_length: Minimum run length before a reset counts as a change point.

    Returns dict:
        - 'change_points': list of int (indices in original series)
        - 'run_lengths': 2D array (T x T) run-length probabilities (lower-triangular)
        - 'map_run_length': array (T,) most probable run length at each t
        - 'n_change_points': int

    Reference:
        Adams & MacKay (2007). "Bayesian Online Changepoint Detection".
        arXiv:0710.3742
    """
    if isinstance(series, pd.Series):
        x = series.values.astype(np.float64)
    else:
        x = np.asarray(series, dtype=np.float64)

    T = len(x)

    # Normal-Gamma conjugate prior parameters
    # mu_0, kappa_0, alpha_0, beta_0
    mu0 = float(prior_mean)
    kappa0 = 1.0
    alpha0_ng = 1.0  # shape parameter for Gamma
    beta0_ng = float(prior_var)  # rate parameter for Gamma

    # run_lengths[t, r] = P(R_t = r | x_{1:t})
    # We store as a dense array but only use lower-triangular part
    run_lengths = np.zeros((T, T + 1))
    run_lengths[0, 0] = 1.0

    # Sufficient statistics per run length hypothesis
    # We maintain arrays indexed by run length r (0..t)
    # Using lists of length T+1 for online updates

    # For each possible run length r at time t:
    #   mu_r, kappa_r, alpha_r, beta_r are Normal-Gamma parameters
    # Initialize for r=0 (new segment)
    mu_r = np.full(T + 1, mu0)
    kappa_r = np.full(T + 1, kappa0)
    alpha_r = np.full(T + 1, alpha0_ng)
    beta_r = np.full(T + 1, beta0_ng)

    map_run_length = np.zeros(T, dtype=np.int32)

    def _student_t_predictive(
        x_t: float, mu: np.ndarray, kappa: np.ndarray, alpha: np.ndarray, beta: np.ndarray
    ) -> np.ndarray:
        """Student-T predictive distribution under Normal-Gamma prior."""
        # P(x | mu, kappa, alpha, beta) = Student-T(2*alpha, mu, beta*(kappa+1)/(kappa*alpha))
        df = 2.0 * alpha
        loc = mu
        scale = np.sqrt(beta * (kappa + 1.0) / (kappa * alpha))
        # Use log-pdf for numerical stability
        from scipy.stats import t as student_t

        # Evaluate PDF at x_t
        log_pred = student_t.logpdf(x_t, df=df, loc=loc, scale=scale)
        return np.exp(log_pred)

    def _gaussian_predictive(
        x_t: float, mu: np.ndarray, kappa: np.ndarray, alpha: np.ndarray, beta: np.ndarray
    ) -> np.ndarray:
        """Gaussian predictive (via marginalizing Normal-Gamma)."""
        # This is also Student-T when marginalizing over unknown mean and variance
        return _student_t_predictive(x_t, mu, kappa, alpha, beta)

    pred_fn = _gaussian_predictive if model == "gaussian" else _student_t_predictive

    h = float(hazard_rate)

    for t in range(1, T):
        x_t = x[t]

        # Current valid run lengths are 0..t-1
        valid_r = t  # indices 0..t-1
        np.arange(valid_r)

        # Predictive probabilities P(x_t | r_{t-1} = r, data)
        pred_probs = pred_fn(
            x_t, mu_r[:valid_r], kappa_r[:valid_r], alpha_r[:valid_r], beta_r[:valid_r]
        )

        # Growth: r_{t-1} -> r_t = r_{t-1} + 1 (no change point)
        growth = run_lengths[t - 1, :valid_r] * pred_probs * (1.0 - h)

        # Reset: change point occurs -> r_t = 0
        # Sum over all previous run lengths
        cp_mass = np.sum(run_lengths[t - 1, :valid_r] * pred_probs * h)

        # New run_length distribution at t
        # r=0: cp_mass (change point happened)
        # r=1..t: growth shifted right
        new_rl = np.zeros(T + 1)
        new_rl[0] = cp_mass
        new_rl[1 : valid_r + 1] = growth

        # Normalize
        total = np.sum(new_rl)
        if total > 0:
            new_rl /= total
        else:
            new_rl[0] = 1.0

        run_lengths[t, :] = new_rl

        # MAP run length at t
        map_run_length[t] = int(np.argmax(new_rl[: t + 1]))

        # Update sufficient statistics for all run lengths
        # For new run length r (starting from 1), the stats are updated from r-1
        # We process in reverse to avoid overwriting

        # Update stats for run lengths 1..t (grew from 0..t-1)
        # kappa_{r+1} = kappa_r + 1
        # mu_{r+1} = (kappa_r * mu_r + x_t) / (kappa_r + 1)
        # alpha_{r+1} = alpha_r + 0.5
        # beta_{r+1} = beta_r + kappa_r*(x_t - mu_r)^2 / (2*(kappa_r+1))

        new_kappa = kappa_r[:valid_r] + 1.0
        new_mu = (kappa_r[:valid_r] * mu_r[:valid_r] + x_t) / new_kappa
        new_alpha = alpha_r[:valid_r] + 0.5
        new_beta = beta_r[:valid_r] + (kappa_r[:valid_r] * (x_t - mu_r[:valid_r]) ** 2) / (
            2.0 * new_kappa
        )

        # Shift right: slot r+1 gets what was r
        kappa_r[1 : valid_r + 1] = new_kappa
        mu_r[1 : valid_r + 1] = new_mu
        alpha_r[1 : valid_r + 1] = new_alpha
        beta_r[1 : valid_r + 1] = new_beta

        # Reset slot 0 to prior (new segment)
        mu_r[0] = mu0
        kappa_r[0] = kappa0
        alpha_r[0] = alpha0_ng
        beta_r[0] = beta0_ng

    # Detect change points: MAP run length resets to near 0 after being > min_segment_length
    change_points: list[int] = []
    for t in range(1, T):
        prev_rl = int(map_run_length[t - 1])
        curr_rl = int(map_run_length[t])
        # Change point: run length drops significantly and previous was long enough
        if curr_rl <= 1 and prev_rl >= min_segment_length:
            change_points.append(t)

    return {
        "change_points": change_points,
        "run_lengths": run_lengths[:T, :T],
        "map_run_length": map_run_length,
        "n_change_points": len(change_points),
    }
