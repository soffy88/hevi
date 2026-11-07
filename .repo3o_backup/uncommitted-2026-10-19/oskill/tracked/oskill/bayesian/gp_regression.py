"""Gaussian Process Regression with RBF, Matern, Rational Quadratic, and Periodic kernels."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.linalg import cho_factor, cho_solve, solve_triangular
from scipy.optimize import minimize

# ---------------------------------------------------------------------------
# Kernel implementations
# ---------------------------------------------------------------------------


def _pairwise_sq_dist(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Compute pairwise squared Euclidean distances between rows of A and B."""
    # ||a - b||^2 = ||a||^2 + ||b||^2 - 2 a·b
    A2 = (A**2).sum(axis=1, keepdims=True)
    B2 = (B**2).sum(axis=1, keepdims=True)
    sq = A2 + B2.T - 2.0 * A @ B.T
    return np.maximum(sq, 0.0)


def _pairwise_dist(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    return np.sqrt(_pairwise_sq_dist(A, B))


def _rbf_kernel(A: np.ndarray, B: np.ndarray, params: dict) -> np.ndarray:
    sigma_f = params.get("sigma_f", 1.0)
    length_scale = params.get("length_scale", 1.0)
    return sigma_f**2 * np.exp(-_pairwise_sq_dist(A, B) / (2.0 * length_scale**2))


def _matern_kernel(A: np.ndarray, B: np.ndarray, params: dict) -> np.ndarray:
    """Matern nu=1.5 kernel."""
    sigma_f = params.get("sigma_f", 1.0)
    length_scale = params.get("length_scale", 1.0)
    r = _pairwise_dist(A, B)
    sqrt3_r_l = np.sqrt(3.0) * r / length_scale
    return sigma_f**2 * (1.0 + sqrt3_r_l) * np.exp(-sqrt3_r_l)


def _rational_quadratic_kernel(A: np.ndarray, B: np.ndarray, params: dict) -> np.ndarray:
    sigma_f = params.get("sigma_f", 1.0)
    length_scale = params.get("length_scale", 1.0)
    alpha = params.get("alpha", 1.0)
    r2 = _pairwise_sq_dist(A, B)
    return sigma_f**2 * (1.0 + r2 / (2.0 * alpha * length_scale**2)) ** (-alpha)


def _periodic_kernel(A: np.ndarray, B: np.ndarray, params: dict) -> np.ndarray:
    sigma_f = params.get("sigma_f", 1.0)
    length_scale = params.get("length_scale", 1.0)
    period = params.get("period", 1.0)
    r = _pairwise_dist(A, B)
    return sigma_f**2 * np.exp(-2.0 * np.sin(np.pi * r / period) ** 2 / length_scale**2)


_KERNEL_FACTORIES = {
    "rbf": _rbf_kernel,
    "matern": _matern_kernel,
    "rational_quadratic": _rational_quadratic_kernel,
    "periodic": _periodic_kernel,
}

_DEFAULT_PARAMS = {
    "rbf": {"sigma_f": 1.0, "length_scale": 1.0},
    "matern": {"sigma_f": 1.0, "length_scale": 1.0},
    "rational_quadratic": {"sigma_f": 1.0, "length_scale": 1.0, "alpha": 1.0},
    "periodic": {"sigma_f": 1.0, "length_scale": 1.0, "period": 1.0},
}

_PARAM_NAMES = {
    "rbf": ["sigma_f", "length_scale"],
    "matern": ["sigma_f", "length_scale"],
    "rational_quadratic": ["sigma_f", "length_scale", "alpha"],
    "periodic": ["sigma_f", "length_scale", "period"],
}


def _log_marginal_likelihood(
    X: np.ndarray,
    y: np.ndarray,
    kernel_fn: Any,
    params: dict,
    noise_variance: float,
) -> float:
    """Compute log marginal likelihood using Cholesky decomposition."""
    n = len(y)
    K = kernel_fn(X, X, params) + (noise_variance + 1e-6) * np.eye(n)
    try:
        L, lower = cho_factor(K, lower=True)
    except np.linalg.LinAlgError:
        return -1e10
    alpha = cho_solve((L, lower), y)
    log_det = 2.0 * np.sum(np.log(np.abs(np.diag(L))))
    lml = -0.5 * y @ alpha - 0.5 * log_det - 0.5 * n * np.log(2.0 * np.pi)
    return float(lml)


def _optimize_hyperparams(
    X: np.ndarray,
    y: np.ndarray,
    kernel: str,
    kernel_params: dict,
    noise_variance: float,
    n_restarts: int,
    rng: np.random.Generator,
) -> tuple[dict, float]:
    """Optimize kernel hyperparameters in log-space using L-BFGS-B."""
    kernel_fn = _KERNEL_FACTORIES[kernel]
    param_names = _PARAM_NAMES[kernel]
    all_vals = [kernel_params[k] for k in param_names] + [noise_variance]

    def neg_lml(log_theta: np.ndarray) -> float:
        theta = np.exp(log_theta)
        params = {k: theta[i] for i, k in enumerate(param_names)}
        nv = theta[-1]
        return -_log_marginal_likelihood(X, y, kernel_fn, params, nv)

    best_lml = -np.inf
    best_theta = np.log(np.array(all_vals) + 1e-10)

    # Initial point from current params
    for restart in range(n_restarts):
        if restart == 0:
            x0 = np.log(np.array(all_vals) + 1e-10)
        else:
            x0 = rng.uniform(-2.0, 2.0, size=len(all_vals))

        try:
            res = minimize(
                neg_lml,
                x0,
                method="L-BFGS-B",
                bounds=[(-5.0, 5.0)] * len(all_vals),
                options={"maxiter": 200, "ftol": 1e-6},
            )
            if res.success and -res.fun > best_lml:
                best_lml = -res.fun
                best_theta = res.x
        except Exception:
            continue

    opt_theta = np.exp(best_theta)
    opt_params = {k: float(opt_theta[i]) for i, k in enumerate(param_names)}
    opt_noise = float(opt_theta[-1])
    return opt_params, opt_noise


def gaussian_process_regression(
    X_train: np.ndarray | pd.DataFrame,
    y_train: np.ndarray | pd.Series,
    X_test: np.ndarray | pd.DataFrame | None = None,
    *,
    kernel: str = "rbf",
    kernel_params: dict | None = None,
    noise_variance: float = 1.0,
    optimize_hyperparameters: bool = True,
    n_restarts: int = 5,
    seed: int | None = None,
) -> dict[str, Any]:
    """Gaussian Process Regression.

    Args:
        X_train: Training inputs (n, d).
        y_train: Training targets (n,).
        X_test: Test inputs (m, d). If None, predicts on training inputs.
        kernel: One of "rbf", "matern", "rational_quadratic", "periodic".
        kernel_params: Dict of kernel hyperparameters.
        noise_variance: Observation noise variance.
        optimize_hyperparameters: If True, optimise kernel params via L-BFGS-B.
        n_restarts: Number of optimisation restarts.
        seed: Random seed for restarts.

    Returns:
        Dict with posterior_mean, posterior_std, posterior_covariance,
        log_marginal_likelihood, optimized_kernel_params, optimized_noise_variance.

    Reference:
        Rasmussen & Williams (2006), "Gaussian Processes for Machine Learning".
    """
    rng = np.random.default_rng(seed)

    def _to_2d(arr: np.ndarray | pd.DataFrame | pd.Series) -> np.ndarray:
        if isinstance(arr, (pd.DataFrame, pd.Series)):
            arr = arr.values
        arr = np.asarray(arr, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        return arr

    X_tr = _to_2d(X_train)
    y_tr = np.asarray(y_train, dtype=np.float64).ravel()
    if isinstance(y_train, pd.Series):
        y_tr = y_train.values.astype(np.float64).ravel()

    X_te = _to_2d(X_test) if X_test is not None else X_tr

    if kernel not in _KERNEL_FACTORIES:
        raise ValueError(f"Unknown kernel: {kernel}. Choose from {list(_KERNEL_FACTORIES)}")

    # Merge default and user-supplied params
    params = {**_DEFAULT_PARAMS[kernel]}
    if kernel_params:
        params.update(kernel_params)

    kernel_fn = _KERNEL_FACTORIES[kernel]

    if optimize_hyperparameters:
        params, noise_variance = _optimize_hyperparams(
            X_tr, y_tr, kernel, params, noise_variance, n_restarts, rng
        )

    n = len(y_tr)
    K_train = kernel_fn(X_tr, X_tr, params) + (noise_variance + 1e-6) * np.eye(n)

    try:
        c_and_lower = cho_factor(K_train, lower=True)
        alpha = cho_solve(c_and_lower, y_tr)
    except np.linalg.LinAlgError:
        K_train += 1e-4 * np.eye(n)
        c_and_lower = cho_factor(K_train, lower=True)
        alpha = cho_solve(c_and_lower, y_tr)

    k_star = kernel_fn(X_te, X_tr, params)
    K_star_star = kernel_fn(X_te, X_te, params)

    post_mean = k_star @ alpha

    # V = L^{-1} k_star.T
    L = c_and_lower[0]
    V = solve_triangular(L, k_star.T, lower=True)
    post_cov = K_star_star - V.T @ V
    post_std = np.sqrt(np.maximum(np.diag(post_cov), 0.0))

    # Log marginal likelihood
    log_det = 2.0 * np.sum(np.log(np.abs(np.diag(L))))
    lml = -0.5 * y_tr @ alpha - 0.5 * log_det - 0.5 * n * np.log(2.0 * np.pi)

    return {
        "posterior_mean": post_mean,
        "posterior_std": post_std,
        "posterior_covariance": post_cov,
        "log_marginal_likelihood": float(lml),
        "optimized_kernel_params": params,
        "optimized_noise_variance": float(noise_variance),
    }
