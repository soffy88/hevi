"""Salience-based asset pricing (Bordalo-Gennaioli-Shleifer 2013 AER)."""

from __future__ import annotations

from typing import Any

import numpy as np

try:
    from oprim.behavioral.salience import salience_function, salience_ranking_weights
except ImportError:

    def salience_function(  # type: ignore[misc]
        payoff: np.ndarray,
        reference: np.ndarray,
        *,
        theta: float = 0.1,
    ) -> np.ndarray:
        payoff_arr = np.asarray(payoff, dtype=float)
        ref_arr = np.asarray(reference, dtype=float)
        numerator = np.abs(payoff_arr - ref_arr)
        denominator = np.abs(payoff_arr) + np.abs(ref_arr) + theta
        return numerator / denominator

    def salience_ranking_weights(  # type: ignore[misc]
        scores: np.ndarray,
        *,
        delta: float = 0.7,
        rank_dim: int = -1,
    ) -> np.ndarray:
        scores = np.asarray(scores, dtype=float)
        order = np.argsort(-scores, axis=rank_dim)
        rank_indices = np.argsort(order, axis=rank_dim)
        unnorm = delta ** rank_indices.astype(float)
        total = unnorm.sum(axis=rank_dim, keepdims=True)
        return unnorm / total


def salience_asset_pricing(
    asset_payoffs: np.ndarray,
    market_payoffs: np.ndarray,
    *,
    risk_free_rate: float = 0.0,
    delta: float = 0.7,
    theta: float = 0.1,
    payoff_probabilities: np.ndarray | None = None,
) -> dict[str, Any]:
    """Salience-based asset pricing (BGS 2013 AER).

    Parameters
    ----------
    asset_payoffs : np.ndarray
        Asset payoffs. Shape (S,) for a single asset or (N, S) for N assets.
    market_payoffs : np.ndarray
        Market/benchmark payoffs. Shape (S,).
    risk_free_rate : float
        Risk-free rate used to discount payoffs to prices.
    delta : float
        Salience diminishing sensitivity parameter in (0, 1]. delta=1 gives
        rational pricing (uniform distortion = no distortion).
    theta : float
        Salience smoothing constant > 0.
    payoff_probabilities : np.ndarray or None
        State probabilities, shape (S,). If None, uniform probabilities are used.

    Returns
    -------
    dict with keys:
        - ``salient_price``: np.ndarray of shape (N,), salient asset prices.
        - ``rational_price``: np.ndarray of shape (N,), rational (EV) prices.
        - ``mispricing``: np.ndarray of shape (N,), salient_price - rational_price.
        - ``distorted_probabilities``: np.ndarray of shape (N, S), per-asset distorted probs.
        - ``salience_scores``: np.ndarray of shape (N, S), salience scores per asset per state.
    """
    asset_payoffs = np.asarray(asset_payoffs, dtype=float)
    market_payoffs = np.asarray(market_payoffs, dtype=float)

    squeezed = asset_payoffs.ndim == 1
    if squeezed:
        asset_payoffs = asset_payoffs[np.newaxis, :]  # (1, S)

    N, S = asset_payoffs.shape

    if market_payoffs.shape != (S,):
        raise ValueError(f"market_payoffs must have shape ({S},), got {market_payoffs.shape}")

    if payoff_probabilities is None:
        probs = np.full(S, 1.0 / S)
    else:
        probs = np.asarray(payoff_probabilities, dtype=float)
        if probs.shape != (S,):
            raise ValueError(f"payoff_probabilities must have shape ({S},), got {probs.shape}")
        probs = probs / probs.sum()  # normalise

    salient_prices = np.empty(N)
    rational_prices = np.empty(N)
    distorted_probs = np.empty((N, S))
    salience_scores = np.empty((N, S))

    for n in range(N):
        payoff_n = asset_payoffs[n]  # (S,)

        # 1. Compute salience scores
        sigma_n = salience_function(payoff_n, reference=market_payoffs, theta=theta)  # (S,)
        salience_scores[n] = sigma_n

        # 2. Rank-order weights from salience
        rank_weights = salience_ranking_weights(sigma_n, delta=delta, rank_dim=-1)  # (S,)

        # 3. Distorted probabilities: element-wise product, then normalize
        pi_tilde = rank_weights * probs
        pi_sum = pi_tilde.sum()
        if pi_sum > 1e-15:
            pi_tilde = pi_tilde / pi_sum
        distorted_probs[n] = pi_tilde

        # 4. Salient price
        salient_prices[n] = float(np.sum(pi_tilde * payoff_n) / (1.0 + risk_free_rate))

        # 5. Rational price
        rational_prices[n] = float(np.sum(probs * payoff_n) / (1.0 + risk_free_rate))

    return {
        "salient_price": salient_prices,
        "rational_price": rational_prices,
        "mispricing": salient_prices - rational_prices,
        "distorted_probabilities": distorted_probs,
        "salience_scores": salience_scores,
    }
