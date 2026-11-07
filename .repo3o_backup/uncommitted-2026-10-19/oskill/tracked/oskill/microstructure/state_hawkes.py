"""State-dependent Hawkes process for order book dynamics.

References
----------
Morariu-Patrichi, M. & Pakkanen, M.S. (2022).
    State-dependent Hawkes processes and their application to limit order book modelling.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.optimize import minimize

_N_STATE_BINS = 5
_LOOKBACK = 100  # events to look back for computational efficiency


def _discretize_states(state_observations: np.ndarray, n_bins: int = _N_STATE_BINS) -> np.ndarray:
    """Discretize continuous state observations into bins via percentiles."""
    percentiles = np.linspace(0, 100, n_bins + 1)
    thresholds = np.percentile(state_observations, percentiles[1:-1])
    return np.digitize(state_observations, thresholds).astype(int)


def _hawkes_nll(
    params: np.ndarray,
    event_times: np.ndarray,
    event_types: np.ndarray,
    state_bins: np.ndarray,
    n_types: int,
    n_bins: int,
    state_function: Literal["multiplicative", "additive"],
) -> float:
    """Negative log-likelihood for state-dependent exponential Hawkes."""
    n_events = len(event_times)
    # Unpack parameters
    mu = params[:n_types]
    alpha_flat = params[n_types : n_types + n_types * n_types]
    alpha = alpha_flat.reshape(n_types, n_types)
    beta = params[n_types + n_types * n_types : n_types + n_types * n_types + n_types]
    state_resp = params[n_types + n_types * n_types + n_types :].reshape(n_bins, n_types)

    eps = 1e-10
    T_total = float(event_times[-1] - event_times[0]) if n_events > 1 else 1.0

    log_lik = 0.0
    integral = 0.0

    for k in range(n_events):
        t_k = event_times[k]
        m_k = event_types[k]
        s_k = state_bins[k]

        # Windowed sum over last LOOKBACK events
        lookback_start = max(0, k - _LOOKBACK)
        intensities = float(mu[m_k])
        for j in range(lookback_start, k):
            dt = t_k - event_times[j]
            m_j = event_types[j]
            intensities += float(alpha[m_j, m_k]) * np.exp(-float(beta[m_k]) * dt)

        if state_function == "multiplicative":
            phi = float(state_resp[s_k, m_k])
            lam = phi * intensities
        else:  # additive
            lam = intensities + float(state_resp[s_k, m_k])

        log_lik += np.log(max(lam, eps))

    # Approximate integral: sum of baselines * T
    for i in range(n_types):
        integral += float(mu[i]) * T_total

    nll = -log_lik + integral
    return float(nll)


def order_book_state_hawkes(
    event_times: np.ndarray,
    event_types: np.ndarray,
    state_observations: np.ndarray,
    *,
    n_event_types: int,
    state_variable: Literal["spread", "imbalance", "depth"] = "imbalance",
    kernel: Literal["exponential", "power_law"] = "exponential",
    state_function: Literal["multiplicative", "additive"] = "multiplicative",
) -> dict[str, Any]:
    """Fit a state-dependent Hawkes process to order book event data.

    Parameters
    ----------
    event_times : np.ndarray
        Strictly increasing 1-D array of event arrival times.
    event_types : np.ndarray
        Integer array of event types in [0, n_event_types-1].
    state_observations : np.ndarray
        State variable observations (same length as event_times).
    n_event_types : int
        Number of distinct event types.
    state_variable : {"spread", "imbalance", "depth"}
        Semantic label for the state variable.
    kernel : {"exponential", "power_law"}
        Excitation kernel type (power_law not implemented; uses exponential).
    state_function : {"multiplicative", "additive"}
        How state modulates baseline intensity.

    Returns
    -------
    dict with keys:
        ``baseline`` — baseline intensities mu, shape (n_event_types,).
        ``excitation`` — excitation matrix alpha, shape (n_types, n_types).
        ``state_response`` — state response factors, shape (n_bins, n_types).
        ``log_likelihood`` — log-likelihood at optimum.
        ``branching_ratio`` — spectral radius of alpha / beta.
    """
    event_times = np.asarray(event_times, dtype=float)
    event_types = np.asarray(event_types, dtype=int)
    state_observations = np.asarray(state_observations, dtype=float)

    if event_times.ndim != 1:
        raise ValueError("event_times must be 1-D")
    if not np.all(np.diff(event_times) > 0):
        raise ValueError("event_times must be strictly increasing")
    if not np.all((event_types >= 0) & (event_types < n_event_types)):
        raise ValueError(f"event_types must be in [0, {n_event_types - 1}]")
    if len(event_times) != len(event_types) or len(event_times) != len(state_observations):
        raise ValueError("event_times, event_types, state_observations must have same length")

    K = n_event_types
    n_bins = _N_STATE_BINS

    # Discretize states
    state_bins = _discretize_states(state_observations, n_bins)

    # Initial parameters: mu (K), alpha (K*K), beta (K), state_resp (n_bins*K)
    x0 = np.concatenate(
        [
            np.full(K, 0.1),  # mu
            0.1 * np.eye(K).ravel(),  # alpha
            np.ones(K),  # beta
            np.ones(n_bins * K),  # state_response
        ]
    )

    # Bounds: mu >= 1e-6, alpha >= 0, beta >= 0.01, state_resp >= 1e-6
    bounds = (
        [(1e-6, None)] * K
        + [(0.0, None)] * (K * K)
        + [(0.01, None)] * K
        + [(1e-6, None)] * (n_bins * K)
    )

    result = minimize(
        _hawkes_nll,
        x0,
        args=(event_times, event_types, state_bins, K, n_bins, state_function),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 200, "ftol": 1e-6},
    )

    params = result.x
    mu = params[:K]
    alpha = params[K : K + K * K].reshape(K, K)
    beta = params[K + K * K : K + K * K + K]
    state_resp = params[K + K * K + K :].reshape(n_bins, K)

    # Branching ratio: spectral radius of alpha / beta (matrix element-wise / row)
    ratio_matrix = alpha / (beta[:, np.newaxis] + 1e-12)
    branching_ratio = float(np.max(np.abs(np.linalg.eigvals(ratio_matrix))))

    return {
        "baseline": mu,
        "excitation": alpha,
        "state_response": state_resp,
        "log_likelihood": float(-result.fun),
        "branching_ratio": branching_ratio,
    }
