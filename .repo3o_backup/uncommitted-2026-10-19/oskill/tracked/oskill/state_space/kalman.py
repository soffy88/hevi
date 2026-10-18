"""Kalman filter and Rauch-Tung-Striebel smoother pipeline."""

from __future__ import annotations

from typing import Any

import numpy as np

from oskill.state_space._base import _kalman_filter_core


def _build_matrices(
    n_state: int,
    obs_dim: int,
    transition_matrix: np.ndarray | None,
    observation_matrix: np.ndarray | None,
    process_noise: float | np.ndarray,
    observation_noise: float | np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build F, H, Q, R matrices from parameters."""
    # Transition matrix F
    if transition_matrix is not None:
        F = np.asarray(transition_matrix, dtype=float)
    else:
        F = np.eye(n_state)

    # Observation matrix H
    if observation_matrix is not None:
        H = np.asarray(observation_matrix, dtype=float)
    else:
        H = np.eye(obs_dim, n_state)

    # Process noise Q
    if np.isscalar(process_noise):
        Q = float(process_noise) * np.eye(n_state)
    else:
        Q = np.asarray(process_noise, dtype=float)
        if Q.ndim == 0:
            Q = float(Q) * np.eye(n_state)
        elif Q.ndim == 1:
            Q = np.diag(Q)

    # Observation noise R
    if np.isscalar(observation_noise):
        R = float(observation_noise) * np.eye(obs_dim)
    else:
        R = np.asarray(observation_noise, dtype=float)
        if R.ndim == 0:
            R = float(R) * np.eye(obs_dim)
        elif R.ndim == 1:
            R = np.diag(R)

    return F, H, Q, R


def kalman_filter_pipeline(
    observations: np.ndarray,
    *,
    transition_matrix: np.ndarray | None = None,
    observation_matrix: np.ndarray | None = None,
    process_noise: float | np.ndarray = 1e-5,
    observation_noise: float | np.ndarray = 1.0,
    initial_state: np.ndarray | None = None,
    initial_covariance: np.ndarray | None = None,
    estimate_params: bool = False,
    max_iter: int = 50,
) -> dict[str, Any]:
    """Kalman filter pipeline.

    For 1-D observations with scalar state (n=1):
    F = [[1]], H = [[1]], Q = [[process_noise]], R = [[observation_noise]].

    Parameters
    ----------
    observations : np.ndarray
        1-D (T,) or 2-D (T, m) observation sequence.
    transition_matrix : np.ndarray, optional
        State transition matrix F (n x n). Defaults to identity.
    observation_matrix : np.ndarray, optional
        Observation matrix H (m x n). Defaults to identity.
    process_noise : float or np.ndarray
        Process noise covariance (scalar, 1-D diagonal, or 2-D matrix).
    observation_noise : float or np.ndarray
        Observation noise covariance (scalar, 1-D diagonal, or 2-D matrix).
    initial_state : np.ndarray, optional
        Initial state mean x0. Defaults to zeros.
    initial_covariance : np.ndarray, optional
        Initial state covariance P0. Defaults to identity.
    estimate_params : bool
        If True, run EM algorithm to estimate Q and R.
    max_iter : int
        Maximum EM iterations (only used if estimate_params=True).

    Returns
    -------
    dict with keys:
        'filtered_states': np.ndarray (T, n)
        'filtered_covariances': np.ndarray (T, n, n)
        'predicted_states': np.ndarray (T, n)
        'predicted_covariances': np.ndarray (T, n, n)
        'log_likelihood': float
        'process_noise': np.ndarray (n, n)
        'observation_noise': np.ndarray (m, m)
        'n_iter': int (EM iterations used, 0 if estimate_params=False)
    """
    obs = np.asarray(observations, dtype=float)
    if obs.ndim == 1:
        obs = obs.reshape(-1, 1)
    T, m = obs.shape

    # Determine state dimension
    if transition_matrix is not None:
        n_state = np.asarray(transition_matrix).shape[0]
    elif observation_matrix is not None:
        n_state = np.asarray(observation_matrix).shape[1]
    else:
        n_state = m  # default: state dim = obs dim

    F, H, Q, R = _build_matrices(
        n_state, m, transition_matrix, observation_matrix, process_noise, observation_noise
    )

    # Initial state and covariance
    x0 = np.zeros(n_state) if initial_state is None else np.asarray(initial_state, dtype=float)
    P0 = (
        np.eye(n_state)
        if initial_covariance is None
        else np.asarray(initial_covariance, dtype=float)
    )

    n_iter = 0

    if estimate_params:
        # Simple EM: iterate over Q and R estimation
        for em_it in range(max_iter):
            xs, Ps, x_preds, P_preds, log_lik = _kalman_filter_core(obs, F, H, Q, R, x0, P0)
            n_iter = em_it + 1

            # M-step: estimate Q and R
            # Q: E[sum (x_t - F*x_{t-1})(x_t - F*x_{t-1})^T] / T
            Q_new = np.zeros_like(Q)
            R_new = np.zeros_like(R)
            for t in range(T):
                inn = obs[t] - H @ xs[t]
                R_new += np.outer(inn, inn) + H @ Ps[t] @ H.T

                if t > 0:
                    diff = xs[t] - F @ xs[t - 1]
                    Q_new += np.outer(diff, diff) + Ps[t] + F @ Ps[t - 1] @ F.T

            Q_new /= max(T - 1, 1)
            R_new /= T

            # Ensure positive definiteness
            Q_new = (Q_new + Q_new.T) / 2 + 1e-10 * np.eye(n_state)
            R_new = (R_new + R_new.T) / 2 + 1e-10 * np.eye(m)

            # Check convergence
            if np.allclose(Q_new, Q, rtol=1e-5) and np.allclose(R_new, R, rtol=1e-5):
                Q, R = Q_new, R_new
                break
            Q, R = Q_new, R_new

    xs, Ps, x_preds, P_preds, log_lik = _kalman_filter_core(obs, F, H, Q, R, x0, P0)

    return {
        "filtered_states": xs,
        "filtered_covariances": Ps,
        "predicted_states": x_preds,
        "predicted_covariances": P_preds,
        "log_likelihood": log_lik,
        "process_noise": Q,
        "observation_noise": R,
        "n_iter": n_iter,
    }


def kalman_smoother(
    observations: np.ndarray,
    filter_result: dict[str, Any] | None = None,
    **filter_kwargs: Any,
) -> dict[str, Any]:
    """Rauch-Tung-Striebel (RTS) smoother.

    Backward smoothing pass after the Kalman filter.
    Uses _kalman_filter_core from _base.py directly (H1: no import of kalman_filter_pipeline).

    Parameters
    ----------
    observations : np.ndarray
        1-D (T,) or 2-D (T, m) observation sequence.
    filter_result : dict, optional
        Pre-computed filter result (from kalman_filter_pipeline).
        If None, filter is run first using filter_kwargs.
    **filter_kwargs
        Keyword arguments passed to the internal filter call
        (process_noise, observation_noise, transition_matrix, etc.)

    Returns
    -------
    dict with keys:
        'smoothed_states': np.ndarray (T, n)
        'smoothed_covariances': np.ndarray (T, n, n)
        'filtered_states': np.ndarray (T, n)   [from forward pass]
        'filtered_covariances': np.ndarray (T, n, n)
        'log_likelihood': float
    """
    obs = np.asarray(observations, dtype=float)
    if obs.ndim == 1:
        obs = obs.reshape(-1, 1)
    T, m = obs.shape

    # Build matrices from filter_kwargs (H1: don't call kalman_filter_pipeline)
    process_noise = filter_kwargs.get("process_noise", 1e-5)
    observation_noise = filter_kwargs.get("observation_noise", 1.0)
    transition_matrix = filter_kwargs.get("transition_matrix", None)
    observation_matrix = filter_kwargs.get("observation_matrix", None)
    initial_state = filter_kwargs.get("initial_state", None)
    initial_covariance = filter_kwargs.get("initial_covariance", None)

    if filter_result is not None:
        # Extract filter outputs from pre-computed result
        xs = filter_result["filtered_states"]
        Ps = filter_result["filtered_covariances"]
        x_preds = filter_result["predicted_states"]
        P_preds = filter_result["predicted_covariances"]
        log_lik = filter_result["log_likelihood"]
        Q = filter_result["process_noise"]
        R = filter_result["observation_noise"]
        n_state = xs.shape[1]
        F_mat = (
            np.asarray(transition_matrix, dtype=float)
            if transition_matrix is not None
            else np.eye(n_state)
        )
    else:
        # Run filter inline using _kalman_filter_core (H1 compliant)
        n_state_guess = (
            np.asarray(transition_matrix).shape[0]
            if transition_matrix is not None
            else (np.asarray(observation_matrix).shape[1] if observation_matrix is not None else m)
        )

        F_mat, H_mat, Q, R = _build_matrices(
            n_state_guess,
            m,
            transition_matrix,
            observation_matrix,
            process_noise,
            observation_noise,
        )
        n_state = n_state_guess

        x0 = np.zeros(n_state) if initial_state is None else np.asarray(initial_state, dtype=float)
        P0 = (
            np.eye(n_state)
            if initial_covariance is None
            else np.asarray(initial_covariance, dtype=float)
        )

        xs, Ps, x_preds, P_preds, log_lik = _kalman_filter_core(obs, F_mat, H_mat, Q, R, x0, P0)

    # --- RTS Backward Smoothing Pass ---
    xs_smooth = xs.copy()
    Ps_smooth = Ps.copy()

    for t in range(T - 2, -1, -1):
        # Smoother gain: G_t = P_t|t * F^T * inv(P_{t+1|t})
        G = Ps[t] @ F_mat.T @ np.linalg.solve(P_preds[t + 1], np.eye(n_state))

        xs_smooth[t] = xs[t] + G @ (xs_smooth[t + 1] - x_preds[t + 1])
        Ps_smooth[t] = Ps[t] + G @ (Ps_smooth[t + 1] - P_preds[t + 1]) @ G.T

    return {
        "smoothed_states": xs_smooth,
        "smoothed_covariances": Ps_smooth,
        "filtered_states": xs,
        "filtered_covariances": Ps,
        "log_likelihood": log_lik,
    }
