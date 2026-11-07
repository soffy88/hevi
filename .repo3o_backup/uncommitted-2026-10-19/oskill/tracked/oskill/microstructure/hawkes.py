"""Hawkes process branching ratio estimator."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from oprim import hawkes_nll
from scipy.optimize import minimize


def hawkes_branching_ratio(
    event_times: np.ndarray,
    *,
    hawkes_params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Estimate Hawkes process branching ratio and stability.

    If hawkes_params is None, fits the Hawkes model via MLE using
    oprim.hawkes_nll (exponential kernel: lambda(t) = mu + sum alpha*exp(-beta*(t-t_i))).

    Parameters
    ----------
    event_times : np.ndarray
        Sorted 1-D array of event arrival times.
    hawkes_params : dict, optional
        Pre-fitted parameters {'mu': float, 'alpha': float, 'beta': float}.
        If None, parameters are estimated from event_times.

    Returns
    -------
    dict with keys:
        'branching_ratio': float — n = alpha / beta
        'stability_status': str — 'stable' / 'near_critical' / 'unstable'
        'hawkes_params': dict — {'mu', 'alpha', 'beta'}
        'half_life': float — ln(2) / beta
    """
    event_times = np.asarray(event_times, dtype=float)

    if hawkes_params is None:
        if len(event_times) < 2:
            # Degenerate case
            hawkes_params = {"mu": 0.1, "alpha": 0.5, "beta": 1.0}
        else:
            T = float(event_times[-1])
            # NOTE: oprim.hawkes_nll uses log-parameterization:
            # params = [log_mu, log_alpha, log_beta]
            x0 = np.array([math.log(0.1), math.log(0.5), math.log(1.0)])
            result = minimize(
                lambda p: hawkes_nll(p, event_times=event_times, t=T),
                x0,
                method="L-BFGS-B",
                options={"maxiter": 500, "ftol": 1e-10},
            )
            mu = float(np.exp(result.x[0]))
            alpha = float(np.exp(result.x[1]))
            beta = float(np.exp(result.x[2]))
            hawkes_params = {"mu": mu, "alpha": alpha, "beta": beta}

    mu = float(hawkes_params["mu"])
    alpha = float(hawkes_params["alpha"])
    beta = float(hawkes_params["beta"])

    n = alpha / beta

    if n < 0.8:
        stability_status = "stable"
    elif n < 1.0:
        stability_status = "near_critical"
    else:
        stability_status = "unstable"

    half_life = math.log(2.0) / beta if beta > 0 else float("inf")

    return {
        "branching_ratio": n,
        "stability_status": stability_status,
        "hawkes_params": {"mu": mu, "alpha": alpha, "beta": beta},
        "half_life": half_life,
    }
