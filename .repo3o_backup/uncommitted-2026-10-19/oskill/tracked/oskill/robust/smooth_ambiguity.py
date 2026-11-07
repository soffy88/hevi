"""Smooth ambiguity portfolio optimization (Klibanoff-Marinacci-Mukerji 2005)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import scipy.optimize


def _eu_model(
    w: np.ndarray,
    rets: np.ndarray,
    utility: str,
    ra: float,
) -> float:
    """Expected utility under a single return model."""
    r = rets @ w  # (T,)
    if utility == "log":
        return float(np.mean(np.log(1.0 + r + 1e-10)))
    else:  # power
        if abs(ra - 1.0) < 1e-8:
            return float(np.mean(np.log(1.0 + r + 1e-10)))
        return float(np.mean((1.0 + r + 1e-10) ** (1.0 - ra) / (1.0 - ra)))


def _phi_fn(x: float, phi_type: str, aa: float) -> float:
    """Ambiguity (phi) function."""
    if phi_type == "exponential":
        return float(-np.exp(-aa * x))
    elif phi_type == "power":
        # Shift to positive domain
        return float((x + 10.0) ** (1.0 - aa) / (1.0 - aa))
    else:  # log
        return float(np.log(max(x + 10.0, 1e-10)))


def _phi_deriv(x: float, phi_type: str, aa: float) -> float:
    """Derivative of phi for model belief distortion."""
    if phi_type == "exponential":
        return float(aa * np.exp(-aa * x))
    elif phi_type == "power":
        return float((x + 10.0) ** (-aa))
    else:  # log
        return float(1.0 / max(x + 10.0, 1e-10))


def smooth_ambiguity_portfolio(
    model_returns: list[np.ndarray],
    *,
    prior_over_models: np.ndarray,
    phi: Literal["log", "power", "exponential"] = "exponential",
    ambiguity_aversion: float = 2.0,
    u_risk_aversion: float = 2.0,
    utility: Literal["log", "power"] = "power",
) -> dict[str, Any]:
    """Smooth ambiguity portfolio optimization (KMM 2005 Econometrica).

    Parameters
    ----------
    model_returns : list of np.ndarray
        K return scenarios, each of shape (T, N). Must all have same shape.
    prior_over_models : np.ndarray
        Prior probability over K models. Must sum to 1.
    phi : {"log", "power", "exponential"}
        Ambiguity (outer) utility function.
    ambiguity_aversion : float
        Ambiguity aversion coefficient. Must be > 0.
    u_risk_aversion : float
        Risk aversion coefficient for the inner utility. Must be > 0.
    utility : {"log", "power"}
        Inner utility function type.

    Returns
    -------
    dict with keys:
        - ``weights``: np.ndarray of shape (N,), optimal portfolio weights.
        - ``expected_utility_by_model``: np.ndarray of shape (K,).
        - ``ambiguity_premium``: float, premium due to ambiguity aversion.
        - ``model_belief_distortion``: np.ndarray of shape (K,), implied posterior.
    """
    # --- Validation ---
    K = len(model_returns)
    if K < 2:
        raise ValueError(f"Need at least 2 models, got {K}")
    prior = np.asarray(prior_over_models, dtype=float)
    if prior.shape != (K,):
        raise ValueError(f"prior_over_models must have shape ({K},), got {prior.shape}")
    if abs(prior.sum() - 1.0) > 1e-8:
        raise ValueError(f"prior_over_models must sum to 1, got {prior.sum():.6f}")
    if ambiguity_aversion <= 0:
        raise ValueError(f"ambiguity_aversion must be > 0, got {ambiguity_aversion!r}")

    ref_shape = model_returns[0].shape
    if len(ref_shape) != 2:
        raise ValueError("Each model_returns array must be 2D (T, N)")
    for k, mr in enumerate(model_returns):
        if mr.shape != ref_shape:
            raise ValueError(f"model_returns[{k}] has shape {mr.shape}, expected {ref_shape}")

    T, N = ref_shape

    # --- KMM objective: V(w) = sum_k prior_k * phi(EU_k(w)) ---
    def kmm_objective(w_arr: np.ndarray) -> float:
        v = 0.0
        for k in range(K):
            eu_k = _eu_model(w_arr, model_returns[k], utility, u_risk_aversion)
            v += prior[k] * _phi_fn(eu_k, phi, ambiguity_aversion)
        return -v  # negate for minimization

    # Constraints and bounds
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0)] * N
    w0 = np.full(N, 1.0 / N)

    result = scipy.optimize.minimize(
        kmm_objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-9, "maxiter": 500},
    )
    w_star = np.clip(result.x, 0.0, 1.0)
    # Re-normalize to sum to 1
    w_sum = w_star.sum()
    if w_sum > 1e-12:
        w_star = w_star / w_sum

    # --- Expected utility by model at w_star ---
    eu_per_model = np.array(
        [_eu_model(w_star, model_returns[k], utility, u_risk_aversion) for k in range(K)]
    )

    # --- Ambiguity premium ---
    smooth_utility = float(-kmm_objective(w_star))  # V(w_star) before negation
    neutral_utility = float(np.sum(prior * eu_per_model))
    ambiguity_premium = smooth_utility - neutral_utility

    # --- Model belief distortion (implied posterior) ---
    phi_primes = np.array([_phi_deriv(eu_per_model[k], phi, ambiguity_aversion) for k in range(K)])
    weighted = phi_primes * prior
    denom = weighted.sum()
    model_belief_distortion = weighted / denom if denom > 1e-15 else prior.copy()

    return {
        "weights": w_star,
        "expected_utility_by_model": eu_per_model,
        "ambiguity_premium": ambiguity_premium,
        "model_belief_distortion": model_belief_distortion,
    }
