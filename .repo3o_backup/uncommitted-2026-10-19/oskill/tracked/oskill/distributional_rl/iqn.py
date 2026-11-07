"""Implicit Quantile Network Loss (Dabney et al. 2018 ICML)."""

from __future__ import annotations

from typing import Literal

import numpy as np

from oskill.distributional_rl.quantile_regression import _pinball_loss


def implicit_quantile_loss(
    predicted_quantiles: np.ndarray,  # (batch, n_sample_quantiles)
    target_quantiles: np.ndarray,  # (batch, n_target_quantiles) or (batch,)
    sample_taus: np.ndarray,  # (batch, n_sample_quantiles)
    target_taus: np.ndarray | None = None,
    *,
    huber_delta: float = 1.0,
    reduction: Literal["mean", "sum", "none"] = "mean",
) -> float | np.ndarray:
    """Implicit Quantile Network (IQN) Loss.

    Computes the IQN loss from Dabney et al. (2018, ICML). For each batch
    element, for each (sample_tau_i, target_quantile_j) pair, computes the
    quantile Huber loss and averages over target and sample quantiles.

    Parameters
    ----------
    predicted_quantiles : np.ndarray, shape (batch, n_sample_quantiles)
        Predicted quantile values at sample_taus.
    target_quantiles : np.ndarray, shape (batch, n_target_quantiles) or (batch,)
        Target quantile values.
    sample_taus : np.ndarray, shape (batch, n_sample_quantiles)
        Quantile levels at which predictions were made, in (0, 1).
    target_taus : np.ndarray or None
        Target quantile levels. If None and target_quantiles is 1-D,
        treated as returns (not quantile-indexed).
    huber_delta : float
        Huber threshold.
    reduction : {"mean", "sum", "none"}
        Reduction over batch dimension.

    Returns
    -------
    float or np.ndarray
        Scalar if reduction in {"mean","sum"}, array of shape (batch,) if "none".

    References
    ----------
    .. [1] Dabney, W. et al. (2018). Implicit Quantile Networks for Distributional
           Reinforcement Learning. ICML 2018.
    """
    pq = np.asarray(predicted_quantiles, dtype=np.float64)
    if pq.ndim == 1:
        pq = pq[np.newaxis, :]
    batch, n_sample = pq.shape

    tq = np.asarray(target_quantiles, dtype=np.float64)
    if tq.ndim == 1:
        # (batch,) → (batch, 1)
        tq = tq[:, np.newaxis]
    tq.shape[1]

    st = np.asarray(sample_taus, dtype=np.float64)
    if st.ndim == 1:
        st = st[np.newaxis, :]
    if st.shape != pq.shape:
        raise ValueError(
            f"sample_taus shape {st.shape} must match predicted_quantiles shape {pq.shape}"
        )

    # u[b, j, i] = target[b, j] - pred[b, i]
    pred_exp = pq[:, np.newaxis, :]  # (batch, 1, n_sample)
    target_exp = tq[:, :, np.newaxis]  # (batch, n_target, 1)
    # sample_taus_exp: (batch, 1, n_sample)
    taus_exp = st[:, np.newaxis, :]  # (batch, 1, n_sample)

    u = target_exp - pred_exp  # (batch, n_target, n_sample)
    losses = _pinball_loss(u, taus_exp, huber_delta)  # (batch, n_target, n_sample)

    # Mean over target (j) and sample (i) quantiles
    per_batch = np.mean(losses, axis=(1, 2))  # (batch,)

    if reduction == "mean":
        return float(np.mean(per_batch))
    elif reduction == "sum":
        return float(np.sum(per_batch))
    else:
        return per_batch
