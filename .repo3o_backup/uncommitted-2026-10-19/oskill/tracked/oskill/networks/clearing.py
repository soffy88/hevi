"""Eisenberg-Noe interbank clearing model."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np


def eisenberg_noe_clearing(
    nominal_liabilities: np.ndarray,
    external_assets: np.ndarray,
    *,
    method: Literal["fictitious_default", "fixed_point"] = "fictitious_default",
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> dict[str, Any]:
    """Compute clearing payment vector via Eisenberg-Noe (2001) algorithm.

    Parameters
    ----------
    nominal_liabilities:
        Non-negative (N, N) matrix L where L[i, j] is nominal liability of i to j.
        Diagonal should be zero.
    external_assets:
        Non-negative vector (N,) of external assets.
    method:
        "fixed_point" uses vanilla contraction iteration;
        "fictitious_default" explicitly tracks default rounds.
    max_iter:
        Maximum iterations.
    tol:
        Convergence tolerance.

    Returns
    -------
    dict with keys: clearing_vector, default_status, iterations, recovery_rates.
    """
    nominal_liabilities = np.asarray(nominal_liabilities, dtype=float)
    external_assets = np.asarray(external_assets, dtype=float)

    ndim_ok = nominal_liabilities.ndim == 2
    square_ok = ndim_ok and (nominal_liabilities.shape[0] == nominal_liabilities.shape[1])
    if not ndim_ok or not square_ok:
        raise ValueError("nominal_liabilities must be square 2-D array")
    N = nominal_liabilities.shape[0]
    if np.any(nominal_liabilities < 0):
        raise ValueError("nominal_liabilities must be non-negative")
    if np.any(external_assets < 0):
        raise ValueError("external_assets must be non-negative")

    L_total = nominal_liabilities.sum(axis=1)  # (N,)
    Pi = nominal_liabilities / np.maximum(L_total[:, None], 1e-12)

    iter_count = 0
    p = L_total.copy()

    if method == "fixed_point":
        for i in range(max_iter):
            p_new = np.minimum(L_total, external_assets + Pi.T @ p)
            err = np.linalg.norm(p_new - p)
            iter_count = i + 1
            p = p_new
            if err < tol:
                break
    else:  # fictitious_default
        active = np.ones(N, dtype=bool)
        for rnd in range(max_iter):
            p_new = np.minimum(L_total, external_assets + Pi.T @ p)
            newly_default = (p_new < L_total - tol) & active
            iter_count = rnd + 1
            if not newly_default.any():
                p = p_new
                break
            active[newly_default] = False
            p = p_new

    default_status = p < L_total * (1 - tol)
    recovery_rates = p / np.maximum(L_total, 1e-12)

    return {
        "clearing_vector": p,
        "default_status": default_status,
        "iterations": iter_count,
        "recovery_rates": recovery_rates,
    }
