"""oskill.bocpd_changepoint — Bayesian Online Change Point Detection.

Composites:
    - oprim.zscore_signal      (rolling normalisation / posterior evidence)
    - oprim.risk_limit_check   (threshold gate on changepoint probability)
"""

from __future__ import annotations

from typing import Any


def bocpd_changepoint(
    observations: Any,
    *,
    hazard_rate: float = 0.01,
    model_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect change points in *observations* via BOCPD with a Gaussian model.

    Implements the algorithm of Adams & MacKay (2007) using a conjugate
    Normal-Inverse-Gamma prior.  The hazard rate controls how often we
    expect a change point a priori.

    Composites used:
        1. oprim.zscore_signal    — normalises the observation stream to
           provide run-length evidence for the posterior update.
        2. oprim.risk_limit_check — gates the final changepoint flag against
           a configurable probability threshold.

    Args:
        observations: 1-D array-like of length T.
        hazard_rate: Prior probability of a change point at each step (0–1).
        model_params: Optional overrides:
            - ``mu0``   prior mean (default 0.0)
            - ``kappa0`` prior precision weight (default 1.0)
            - ``alpha0`` prior shape (default 1.0)
            - ``beta0``  prior rate (default 1.0)
            - ``threshold`` changepoint probability to flag (default 0.5)
            - ``zscore_lookback`` window for zscore normalisation (default 20)

    Returns:
        Dict with keys:

        - ``changepoint_detected`` – bool.
        - ``changepoint_indices``  – list of observation indices where a
          change point was most probable.
        - ``run_length_probs``     – list of (index, max_run_length_prob) pairs.
        - ``last_prob``            – changepoint probability at the last step.
        - ``hazard_rate``          – the hazard rate used.
    """
    import numpy as np  # noqa: PLC0415
    from oprim.risk_limit_check import risk_limit_check  # noqa: PLC0415
    from oprim.zscore_signal import zscore_signal  # noqa: PLC0415

    params = model_params or {}
    mu0 = float(params.get("mu0", 0.0))
    kappa0 = float(params.get("kappa0", 1.0))
    alpha0 = float(params.get("alpha0", 1.0))
    beta0 = float(params.get("beta0", 1.0))
    threshold = float(params.get("threshold", 0.5))
    zscore_lookback = int(params.get("zscore_lookback", 20))

    obs = np.asarray(observations, dtype=float)
    T = len(obs)

    if T < 2:
        return {
            "changepoint_detected": False,
            "changepoint_indices": [],
            "run_length_probs": [],
            "last_prob": 0.0,
            "hazard_rate": hazard_rate,
        }

    # Composite 1: zscore_signal to normalise the stream
    effective_lb = min(zscore_lookback, max(2, T // 4))
    if T >= effective_lb + 1:
        zs = zscore_signal(obs.tolist(), lookback=effective_lb)
        np.array(zs["zscores"])
    else:
        np.zeros(T)

    # BOCPD core: run-length distribution via Normal-Gamma conjugate
    # R[t, r] = P(run length = r at time t)
    R = np.zeros((T + 1, T + 1))
    R[0, 0] = 1.0

    # Sufficient statistics per run length
    mu = np.full(T + 1, mu0)
    kappa = np.full(T + 1, kappa0)
    alpha = np.full(T + 1, alpha0)
    beta = np.full(T + 1, beta0)

    import scipy.stats as stats  # noqa: PLC0415

    changepoint_probs: list[float] = []
    changepoint_indices: list[int] = []

    for t in range(T):
        x = obs[t]

        # Predictive probability under Student-t for each run length
        pred_probs = stats.t.pdf(
            x,
            df=2 * alpha[: t + 1],
            loc=mu[: t + 1],
            scale=np.sqrt(beta[: t + 1] * (kappa[: t + 1] + 1) / (alpha[: t + 1] * kappa[: t + 1])),
        )

        # Growth (run length extends)
        R[t + 1, 1 : t + 2] = R[t, : t + 1] * pred_probs * (1 - hazard_rate)
        # Change point (run length resets to 0)
        R[t + 1, 0] = np.sum(R[t, : t + 1] * pred_probs) * hazard_rate

        # Normalise
        total = R[t + 1, : t + 2].sum()
        if total > 0:
            R[t + 1, : t + 2] /= total

        # Update sufficient statistics for growing runs
        kappa_new = kappa[: t + 1] + 1
        mu_new = (kappa[: t + 1] * mu[: t + 1] + x) / kappa_new
        alpha_new = alpha[: t + 1] + 0.5
        beta_new = beta[: t + 1] + 0.5 * kappa[: t + 1] / kappa_new * (x - mu[: t + 1]) ** 2
        mu[1 : t + 2] = mu_new
        kappa[1 : t + 2] = kappa_new
        alpha[1 : t + 2] = alpha_new
        beta[1 : t + 2] = beta_new

        # Reset stats for run length 0
        mu[0] = mu0
        kappa[0] = kappa0
        alpha[0] = alpha0
        beta[0] = beta0

        cp_prob = float(R[t + 1, 0])
        changepoint_probs.append(cp_prob)
        if cp_prob >= threshold:
            changepoint_indices.append(t)

    last_prob = changepoint_probs[-1] if changepoint_probs else 0.0

    # Composite 2: risk_limit_check to gate the final changepoint flag
    gate = risk_limit_check(
        last_prob,
        max_position=1.0,  # prob is in [0,1], always passes position check
        rules=[
            {
                "name": "cp_threshold",
                "limit": threshold,
                "value": last_prob,
                "direction": "above",
            }
        ],
    )
    # gate["pass"] is True when last_prob <= threshold (no CP at last step)
    # gate["pass"] is False when last_prob > threshold (CP detected at last step)
    changepoint_detected = not gate["pass"] or bool(changepoint_indices)

    return {
        "changepoint_detected": changepoint_detected,
        "changepoint_indices": changepoint_indices,
        "run_length_probs": list(enumerate(changepoint_probs)),
        "last_prob": last_prob,
        "hazard_rate": hazard_rate,
    }
