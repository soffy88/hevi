"""Shared Kalman filter core logic for state_space module.

This module provides _kalman_filter_core which is used by both
kalman.py (kalman_filter_pipeline, kalman_smoother) and
is importable without creating circular sibling imports.

H2 exemption: this helper module does not count towards element limits.
"""

from __future__ import annotations

import numpy as np


def _kalman_filter_core(
    observations: np.ndarray,
    F: np.ndarray,
    H: np.ndarray,
    Q: np.ndarray,
    R: np.ndarray,
    x0: np.ndarray,
    P0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    """Run Kalman filter predict/update loop.

    Parameters
    ----------
    observations : np.ndarray, shape (T, m)
        Observation sequence.
    F : np.ndarray, shape (n, n)
        State transition matrix.
    H : np.ndarray, shape (m, n)
        Observation matrix.
    Q : np.ndarray, shape (n, n)
        Process noise covariance.
    R : np.ndarray, shape (m, m)
        Observation noise covariance.
    x0 : np.ndarray, shape (n,)
        Initial state estimate.
    P0 : np.ndarray, shape (n, n)
        Initial state covariance.

    Returns
    -------
    xs : np.ndarray, shape (T, n) — filtered state estimates
    Ps : np.ndarray, shape (T, n, n) — filtered covariances
    x_preds : np.ndarray, shape (T, n) — predicted states (for smoother)
    P_preds : np.ndarray, shape (T, n, n) — predicted covariances (for smoother)
    log_lik : float — total log-likelihood
    """
    T = len(observations)
    n = len(x0)
    m = H.shape[0]

    xs = np.zeros((T, n))
    Ps = np.zeros((T, n, n))
    x_preds = np.zeros((T, n))
    P_preds = np.zeros((T, n, n))
    log_lik = 0.0

    x = x0.copy()
    P = P0.copy()

    for t in range(T):
        # --- Predict ---
        x_pred = F @ x
        P_pred = F @ P @ F.T + Q

        x_preds[t] = x_pred
        P_preds[t] = P_pred

        # --- Update ---
        y = observations[t]
        if y.ndim == 0:
            y = y.reshape(1)

        inn = y - H @ x_pred  # innovation
        S = H @ P_pred @ H.T + R  # innovation covariance
        K = P_pred @ H.T @ np.linalg.solve(S, np.eye(m))  # Kalman gain

        x = x_pred + K @ inn
        P = (np.eye(n) - K @ H) @ P_pred

        xs[t] = x
        Ps[t] = P

        # Log-likelihood contribution
        sign, logdet = np.linalg.slogdet(S)
        if sign > 0:
            log_lik += -0.5 * (logdet + inn @ np.linalg.solve(S, inn) + m * np.log(2 * np.pi))

    return xs, Ps, x_preds, P_preds, log_lik
