"""Quantile Regression Loss for Distributional RL (Dabney et al. 2018)."""

from __future__ import annotations

from typing import Literal

import numpy as np


def _huber_loss(u: np.ndarray, delta: float) -> np.ndarray:
    """Huber loss element-wise.

    huber(u) = 0.5*u^2        if |u| <= delta
               delta*(|u| - 0.5*delta)  otherwise
    """
    abs_u = np.abs(u)
    return np.where(abs_u <= delta, 0.5 * u**2, delta * (abs_u - 0.5 * delta))


def _pinball_loss(
    u: np.ndarray,
    tau: np.ndarray,
    huber_delta: float,
) -> np.ndarray:
    """Quantile Huber (pinball) loss element-wise.

    rho_tau(u) = |tau - (u < 0)| * huber(u) / max(huber_delta, eps)

    For huber_delta effectively 0, degenerates to standard pinball.
    """
    if huber_delta <= 0:
        # Standard pinball loss: tau*u if u>=0, (tau-1)*u if u<0
        return np.where(u >= 0, tau * u, (tau - 1) * u)
    indicator = (u < 0).astype(np.float64)
    weight = np.abs(tau - indicator)
    h = _huber_loss(u, huber_delta)
    return weight * h / huber_delta


def quantile_regression_loss(
    predicted_quantiles: np.ndarray,  # shape (batch, n_quantiles)
    target_returns: np.ndarray,  # shape (batch,) or (batch, n_quantiles)
    quantile_levels: np.ndarray | None = None,
    *,
    huber_delta: float = 1.0,
    reduction: Literal["mean", "sum", "none"] = "mean",
) -> float | np.ndarray:
    """Quantile Regression Loss for Distributional RL (QR-DQN).

    Computes the quantile Huber loss from Dabney et al. (2018).

    Parameters
    ----------
    predicted_quantiles : np.ndarray, shape (batch, n_quantiles)
        Predicted quantile values. Each row is a distribution over n_quantiles.
    target_returns : np.ndarray, shape (batch,) or (batch, n_quantiles)
        Target returns. If 1-D, broadcast to (batch, n_quantiles).
    quantile_levels : np.ndarray or None
        Quantile levels tau in (0, 1), shape (n_quantiles,).
        Default: uniform midpoints [1/(2N), 3/(2N), ..., (2N-1)/(2N)].
    huber_delta : float
        Huber threshold. If <= 0, uses standard pinball loss.
    reduction : {"mean", "sum", "none"}
        Reduction over batch dimension.

    Returns
    -------
    float or np.ndarray
        Scalar if reduction in {"mean","sum"}, array of shape (batch,) if "none".

    References
    ----------
    .. [1] Dabney, W. et al. (2018). Distributional Reinforcement Learning with
           Quantile Regression. AAAI 2018.
    """
    pq = np.asarray(predicted_quantiles, dtype=np.float64)
    if pq.ndim == 1:
        pq = pq[np.newaxis, :]  # (1, N)
    batch, n_q = pq.shape

    tr = np.asarray(target_returns, dtype=np.float64)
    if tr.ndim == 1:
        # (batch,) → (batch, n_q)
        tr = np.tile(tr[:, np.newaxis], (1, n_q))
    elif tr.ndim == 2 and tr.shape == (batch, 1):
        tr = np.tile(tr, (1, n_q))

    if quantile_levels is None:
        # Uniform midpoints
        taus = (2 * np.arange(1, n_q + 1) - 1) / (2 * n_q)  # shape (n_q,)
    else:
        taus = np.asarray(quantile_levels, dtype=np.float64)
        if len(taus) != n_q:
            raise ValueError(f"quantile_levels length {len(taus)} does not match n_quantiles {n_q}")

    # u[b, j, i] = target[b, j] - pred[b, i]
    # pq: (batch, n_q=i), tr: (batch, n_q=j)
    # Expand: pred (batch, 1, n_q), target (batch, n_q, 1)
    pred_exp = pq[:, np.newaxis, :]  # (batch, 1, n_q)
    target_exp = tr[:, :, np.newaxis]  # (batch, n_q, 1)
    taus_exp = taus[np.newaxis, np.newaxis, :]  # (1, 1, n_q)

    u = target_exp - pred_exp  # (batch, n_q_target, n_q_pred)
    losses = _pinball_loss(u, taus_exp, huber_delta)  # (batch, n_q, n_q)

    # Mean over target quantiles (j) and pred quantiles (i)
    per_batch = np.mean(losses, axis=(1, 2))  # (batch,)

    if reduction == "mean":
        return float(np.mean(per_batch))
    elif reduction == "sum":
        return float(np.sum(per_batch))
    else:
        return per_batch
