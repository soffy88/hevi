"""Random Matrix Theory denoising of covariance matrix."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd


def denoised_covariance(
    returns: np.ndarray | pd.DataFrame,
    *,
    method: Literal["mp_filter", "constant_residual"] = "mp_filter",
    bandwidth: float | None = None,
) -> dict[str, Any]:
    """Random Matrix Theory denoising of covariance matrix.

    Marchenko-Pastur filter:
        1. Compute correlation matrix C
        2. Eigendecompose: eigenvalues, eigenvectors
        3. MP upper bound: lambda_+ = (1 + sqrt(N/T))^2
           (sigma^2 assumed 1 after standardization)
        4. Replace eigenvalues <= lambda_+ with their average (preserve trace)
        5. Reconstruct denoised correlation, convert to covariance

    Returns dict:
        covariance:             np.ndarray (N x N) denoised covariance
        correlation:            np.ndarray (N x N) denoised correlation
        eigenvalues_original:   np.ndarray (N,) original eigenvalues
        eigenvalues_denoised:   np.ndarray (N,) denoised eigenvalues
        lambda_plus:            float MP upper bound
        n_signal_eigenvalues:   int number of signal (non-noise) eigenvalues

    Reference:
        López de Prado (2020), "Machine Learning for Asset Managers", Ch.2
        Marchenko & Pastur (1967)

    Args:
        returns: T x N returns matrix (numpy array or DataFrame).
        method: Denoising method ("mp_filter" or "constant_residual").
        bandwidth: Optional bandwidth parameter (unused currently, for KDE fitting).

    Raises:
        ValueError: If T < N + 10.
    """
    # Handle DataFrame input
    if isinstance(returns, pd.DataFrame):
        data = returns.values.astype(np.float64)
    else:
        data = np.asarray(returns, dtype=np.float64)

    if data.ndim == 1:
        data = data.reshape(-1, 1)

    T, N = data.shape

    if T < N + 10:
        raise ValueError(f"Insufficient data: T={T} must be >= N+10={N + 10} for denoising")

    # Standardize: zero mean, unit variance
    mu = data.mean(axis=0)
    sigma = data.std(axis=0, ddof=1)
    sigma_safe = np.where(sigma == 0, 1.0, sigma)
    X = (data - mu) / sigma_safe

    # Compute correlation matrix
    C = np.corrcoef(X.T)
    # Ensure symmetry
    C = (C + C.T) / 2.0

    # Eigendecomposition (eigh returns sorted ascending)
    eigenvalues_orig, eigenvectors = np.linalg.eigh(C)
    eigenvalues_orig = np.real(eigenvalues_orig)
    eigenvectors = np.real(eigenvectors)

    # Marchenko-Pastur upper bound: lambda_+ = (1 + sqrt(N/T))^2
    q = T / N  # ratio T/N (should be > 1)
    lambda_plus = (1.0 + np.sqrt(1.0 / q)) ** 2

    # Identify noise vs signal eigenvalues
    # Noise: eigenvalue <= lambda_plus
    noise_mask = eigenvalues_orig <= lambda_plus
    signal_mask = ~noise_mask
    n_signal = int(np.sum(signal_mask))

    # Denoise: replace noise eigenvalues
    eigenvalues_denoised = eigenvalues_orig.copy()

    if np.any(noise_mask):
        noise_evs = eigenvalues_orig[noise_mask]
        n_noise = len(noise_evs)

        if method == "mp_filter":
            # Replace all noise eigenvalues with their mean, preserving trace
            mean_noise = float(np.mean(noise_evs))
            eigenvalues_denoised[noise_mask] = mean_noise
        elif method == "constant_residual":
            # Replace noise eigenvalues with single constant = sum/n_noise
            constant_ev = float(np.sum(noise_evs) / n_noise)
            eigenvalues_denoised[noise_mask] = constant_ev
        else:
            raise ValueError(f"Unknown method: {method!r}")

    # Ensure PSD: clip negative eigenvalues to 0
    eigenvalues_denoised = np.maximum(eigenvalues_denoised, 0.0)

    # Reconstruct denoised correlation matrix
    C_denoised = eigenvectors @ np.diag(eigenvalues_denoised) @ eigenvectors.T
    # Ensure symmetry
    C_denoised = (C_denoised + C_denoised.T) / 2.0

    # Normalize to ensure diagonal is 1 (correlation matrix property)
    diag_sqrt = np.sqrt(np.maximum(np.diag(C_denoised), 1e-14))
    C_denoised_normalized = C_denoised / np.outer(diag_sqrt, diag_sqrt)
    np.fill_diagonal(C_denoised_normalized, 1.0)

    # Final PSD check on normalized correlation
    evs_check = np.linalg.eigvalsh(C_denoised_normalized)
    if np.any(evs_check < -1e-10):  # pragma: no cover
        # Force PSD via eigenvalue clipping
        ev2, vec2 = np.linalg.eigh(C_denoised_normalized)
        ev2 = np.maximum(ev2, 0.0)
        C_denoised_normalized = vec2 @ np.diag(ev2) @ vec2.T
        C_denoised_normalized = (C_denoised_normalized + C_denoised_normalized.T) / 2.0
        np.fill_diagonal(C_denoised_normalized, 1.0)

    # Convert correlation back to covariance: C_denoised * outer(std, std)
    cov_denoised = C_denoised_normalized * np.outer(sigma_safe, sigma_safe)

    return {
        "covariance": cov_denoised,
        "correlation": C_denoised_normalized,
        "eigenvalues_original": eigenvalues_orig,
        "eigenvalues_denoised": eigenvalues_denoised,
        "lambda_plus": float(lambda_plus),
        "n_signal_eigenvalues": n_signal,
    }
