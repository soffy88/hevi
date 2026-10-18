"""Causal inference workflows built on oprim primitives."""

from __future__ import annotations

import numpy as np
from oprim import ordinal_pattern, phase_randomize


def symbolic_transfer_entropy(
    source: np.ndarray,
    target: np.ndarray,
    d: int = 3,
    lag: int = 1,
    n_surrogates: int = 0,
    alpha: float = 0.05,
    random_state: int | None = None,
) -> dict:
    """Symbolic Transfer Entropy from source → target.

    Uses ordinal pattern encoding (Bandt-Pompe) and conditional entropy.
    Optionally performs surrogate significance test via phase randomization.

    Parameters
    ----------
    source, target : np.ndarray
        1-D time series (same length).
    d : int
        Ordinal pattern embedding dimension.
    lag : int
        Transfer lag.
    n_surrogates : int
        If > 0, perform phase-randomization significance test.
    alpha : float
        Significance level for surrogate test.
    random_state : int, optional
        RNG seed.

    Returns
    -------
    dict
        "te": transfer entropy (bits), "p_value": (if surrogates > 0),
        "significant": bool (if surrogates > 0).

    References
    ----------
    .. [1] Schreiber, T. (2000). Measuring information transfer.
    .. [2] Staniek, M. & Lehnertz, K. (2008). Symbolic transfer entropy.
    .. [3] Extraction source: Selene project, sel_v2/offline/transfer_entropy.py:symbolic_te
    """
    sx = ordinal_pattern(source, d=d)
    sy = ordinal_pattern(target, d=d)

    te = _compute_ste(sx, sy, d, lag)

    result = {"te": te}

    if n_surrogates > 0:
        rng = np.random.default_rng(random_state)
        surr_tes = []
        for _ in range(n_surrogates):
            surr_source = phase_randomize(source, rng=rng)
            surr_sx = ordinal_pattern(surr_source, d=d)
            surr_te = _compute_ste(surr_sx, sy, d, lag)
            surr_tes.append(surr_te)
        p_value = float(np.mean(np.array(surr_tes) >= te))
        result["p_value"] = p_value
        result["significant"] = p_value < alpha

    return result


def _compute_ste(sx: np.ndarray, sy: np.ndarray, d: int, lag: int) -> float:
    """Core STE computation from pre-encoded ordinal patterns."""
    n = min(len(sx), len(sy)) - lag
    if n <= 0:
        return 0.0

    y_fut = sy[d : d + n]
    y_past = sy[d - 1 : d - 1 + n]
    x_past = sx[d - 1 : d - 1 + n]

    min_len = min(len(y_fut), len(y_past), len(x_past))
    y_fut = y_fut[:min_len]
    y_past = y_past[:min_len]
    x_past = x_past[:min_len]

    if min_len < 10:
        return 0.0

    n_sym = int(max(y_fut.max(), y_past.max(), x_past.max())) + 1

    # Joint symbols via Cantor-style pairing
    jYtYp = y_fut * n_sym + y_past
    jYpXp = y_past * n_sym + x_past
    jAll = y_fut * (n_sym * n_sym) + y_past * n_sym + x_past

    # H(Y_t | Y_past) = H(Y_t, Y_past) - H(Y_past)
    h_yt_yp = _H_arr(jYtYp) - _H_arr(y_past)
    # H(Y_t | Y_past, X_past) = H(Y_t, Y_past, X_past) - H(Y_past, X_past)
    h_yt_yp_xp = _H_arr(jAll) - _H_arr(jYpXp)

    return max(0.0, h_yt_yp - h_yt_yp_xp)


def _H_arr(x: np.ndarray) -> float:
    """Shannon entropy in bits from integer array."""
    counts = np.bincount(x)
    probs = counts[counts > 0] / len(x)
    return float(-np.sum(probs * np.log2(probs)))
