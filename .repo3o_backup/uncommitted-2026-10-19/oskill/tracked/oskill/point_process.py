"""Point process workflows built on oprim primitives."""

from __future__ import annotations

import numpy as np
from oprim import hawkes_nll
from scipy.optimize import minimize


def fit_hawkes(
    event_times: np.ndarray,
    T: float,
    n_restarts: int = 5,
    random_state: int = 42,
) -> dict:
    """Fit exponential Hawkes process via MLE with random restarts.

    Uses oprim.hawkes_nll as the objective function.

    Parameters
    ----------
    event_times : np.ndarray
        Sorted 1-D array of event times.
    T : float
        Observation window end time.
    n_restarts : int
        Number of random initializations.
    random_state : int
        RNG seed for reproducibility.

    Returns
    -------
    dict
        "converged", "mu", "alpha", "beta", "branching_ratio", "nll".

    References
    ----------
    .. [1] Hawkes, A.G. (1971). Spectra of some self-exciting and mutually exciting point processes.
    .. [2] Extraction source: Selene project, sel_v2/hawkes/mle.py:fit_hawkes
    """
    if len(event_times) < 5:
        return {"converged": False, "branching_ratio": float("nan")}

    rng = np.random.default_rng(random_state)
    best_result = None
    best_nll = np.inf

    for _ in range(n_restarts):
        x0 = np.array(
            [
                rng.uniform(-5, -1),
                rng.uniform(-5, -1),
                rng.uniform(-3, 1),
            ]
        )
        try:
            result = minimize(
                hawkes_nll,
                x0,
                args=(event_times, T),
                method="Nelder-Mead",
                options={"maxiter": 2000, "xatol": 1e-6, "fatol": 1e-6},
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None:
        return {"converged": False, "branching_ratio": float("nan")}

    mu = np.exp(best_result.x[0])
    alpha = np.exp(best_result.x[1])
    beta = np.exp(best_result.x[2])
    br = alpha / beta

    return {
        "converged": bool(best_result.success),
        "mu": float(mu),
        "alpha": float(alpha),
        "beta": float(beta),
        "branching_ratio": float(br) if np.isfinite(br) else float("nan"),
        "nll": float(best_nll),
    }
