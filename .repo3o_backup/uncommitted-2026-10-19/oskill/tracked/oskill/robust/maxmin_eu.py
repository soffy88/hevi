"""Max-min expected utility portfolio optimization under model uncertainty."""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.optimize import minimize


def _expected_utility(
    w: np.ndarray,
    rets: np.ndarray,
    utility: str,
    risk_aversion: float,
) -> float:
    """Compute expected utility for a single scenario."""
    port_returns = rets @ w  # (T,)
    if utility == "log":
        return float(np.mean(np.log(1 + port_returns + 1e-10)))
    elif utility == "power":
        if abs(risk_aversion - 1.0) < 1e-8:
            return float(np.mean(np.log(1 + port_returns + 1e-10)))
        return float(np.mean((1 + port_returns) ** (1 - risk_aversion)) / (1 - risk_aversion))
    else:  # exponential
        return float(-np.mean(np.exp(-risk_aversion * port_returns)) / risk_aversion)


def maxmin_expected_utility_portfolio(
    return_scenarios: list[np.ndarray],
    *,
    utility: Literal["log", "power", "exponential"] = "log",
    risk_aversion: float = 2.0,
    prior_weights: np.ndarray | None = None,
    method: Literal["maxmin", "alpha_maxmin"] = "maxmin",
    alpha: float = 0.5,
) -> dict[str, object]:
    """Find the portfolio that maximizes worst-case (or alpha-weighted) expected utility.

    Parameters
    ----------
    return_scenarios:
        List of K arrays each shaped (T, N). All must share the same N.
    utility:
        Utility function type: "log", "power", or "exponential".
    risk_aversion:
        Risk aversion parameter for power/exponential utilities.
    prior_weights:
        Optional K-vector of prior scenario weights (ignored in computation currently).
    method:
        "maxmin" maximizes worst-case EU; "alpha_maxmin" blends min and max.
    alpha:
        Weight on worst-case in alpha_maxmin: alpha*min + (1-alpha)*max.

    Returns
    -------
    dict with keys: weights, worst_case_utility, worst_prior_index, utilities_by_prior.
    """
    if len(return_scenarios) < 2:
        raise ValueError("Need at least 2 scenarios")

    scenarios = [np.asarray(s, dtype=float) for s in return_scenarios]
    T0, N = scenarios[0].shape
    for i, s in enumerate(scenarios[1:], 1):
        if s.shape[1] != N:
            raise ValueError(f"Scenario {i} has {s.shape[1]} assets, expected {N}")

    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0)] * N
    w0 = np.ones(N) / N

    def objective(w: np.ndarray) -> float:
        eus = [_expected_utility(w, s, utility, risk_aversion) for s in scenarios]
        if method == "maxmin":
            return -min(eus)
        else:  # alpha_maxmin
            return -(alpha * min(eus) + (1 - alpha) * max(eus))

    result = minimize(
        objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-10},
    )
    w_opt = result.x
    w_opt = np.clip(w_opt, 0.0, 1.0)
    w_opt /= w_opt.sum() + 1e-12

    eu_per_scenario = [_expected_utility(w_opt, s, utility, risk_aversion) for s in scenarios]
    worst_idx = int(np.argmin(eu_per_scenario))
    worst_eu = eu_per_scenario[worst_idx]

    return {
        "weights": w_opt,
        "worst_case_utility": float(worst_eu),
        "worst_prior_index": worst_idx,
        "utilities_by_prior": eu_per_scenario,
    }
