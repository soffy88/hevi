"""Signature-based option pricing via functional linear regression."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

try:
    from oprim.signature.compute import path_signature_compute

    _HAS_SIGNATURE = True
except ImportError:
    _HAS_SIGNATURE = False


def _compute_sig(path: np.ndarray, depth: int) -> np.ndarray:
    """Minimal truncated signature computation (fallback, no oprim dependency)."""
    n, d = path.shape
    increments = np.diff(path, axis=0)
    running: list[np.ndarray] = [np.ones(1)] + [np.zeros(d**k) for k in range(1, depth + 1)]
    for t in range(len(increments)):
        dx = increments[t]
        for k in range(depth, 0, -1):
            running[k] = running[k] + np.outer(running[k - 1], dx).ravel()
    return np.concatenate(running)


def _get_signature(path: np.ndarray, depth: int) -> np.ndarray:
    """Compute truncated signature, using oprim if available."""
    if _HAS_SIGNATURE:
        return path_signature_compute(path, truncation_depth=depth)["signature"]
    return _compute_sig(path, depth)


def signature_based_pricing(
    historical_paths: np.ndarray,
    option_payoff_fn: Callable[[np.ndarray], float],
    *,
    truncation_depth: int = 6,
    n_basis_paths: int = 1000,
    method: str = "ridge",
    regularization: float = 0.01,
) -> dict[str, Any]:
    """Price a path-dependent option via signature-based functional linear regression.

    Fits a linear functional from the truncated path signature to the option payoff,
    enabling non-parametric pricing of exotic options such as Asian and barrier contracts.

    Parameters
    ----------
    historical_paths:
        Array of shape (n_paths, n_steps, dim) of simulated or historical price paths.
    option_payoff_fn:
        Callable mapping a single path array of shape (n_steps, dim) to a float payoff.
    truncation_depth:
        Truncation level for the tensor-series signature expansion.
    n_basis_paths:
        Maximum number of paths to use for regression fitting.
    method:
        Regression method: ``"ridge"``, ``"lasso"``, or ``"ols"``.
    regularization:
        Regularization strength (alpha) for Ridge/Lasso.

    Returns
    -------
    dict with keys:
        pricing_functional, signature_depth, in_sample_r_squared,
        training_payoffs, training_predictions, method, price_fn, fingerprint.
    """
    import oprim
    from sklearn.linear_model import Lasso, LinearRegression, Ridge

    historical_paths = np.asarray(historical_paths, dtype=float)
    n_paths, n_steps, dim = historical_paths.shape

    # Subsample if needed
    if n_paths > n_basis_paths:
        idx = np.random.default_rng(42).choice(n_paths, n_basis_paths, replace=False)
        basis_paths = historical_paths[idx]
    else:
        basis_paths = historical_paths

    # Compute signatures and payoffs
    sigs = []
    for path in basis_paths:
        sigs.append(_get_signature(path, truncation_depth))

    X = np.array(sigs)  # (n_basis, sig_length)
    y = np.array([float(option_payoff_fn(path)) for path in basis_paths])

    # Fit linear model
    if method == "ridge":
        model = Ridge(alpha=regularization)
    elif method == "lasso":
        model = Lasso(alpha=regularization)
    else:
        model = LinearRegression()

    model.fit(X, y)
    coeff = model.coef_

    y_pred = model.predict(X)
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    def price_fn(new_path: np.ndarray) -> float:
        new_path = np.asarray(new_path, dtype=float)
        s = _get_signature(new_path, truncation_depth)
        return float(model.predict(s.reshape(1, -1))[0])

    fp = oprim.sha256_hash(oprim.canonical_json({"coeff_sum": float(np.sum(coeff)), "r_sq": r_sq}))

    return {
        "pricing_functional": coeff,
        "signature_depth": truncation_depth,
        "in_sample_r_squared": r_sq,
        "training_payoffs": y,
        "training_predictions": y_pred,
        "method": method,
        "price_fn": price_fn,
        "fingerprint": fp,
    }
