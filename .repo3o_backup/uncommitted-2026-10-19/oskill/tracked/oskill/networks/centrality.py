"""Financial network centrality metrics."""

from __future__ import annotations

from typing import Literal

import numpy as np


def financial_network_centrality(
    exposure_matrix: np.ndarray,
    *,
    metrics: list[Literal["debt_rank", "eigenvector", "katz", "betweenness"]] | None = None,
    damping: float = 0.85,
) -> dict[str, np.ndarray]:
    """Compute centrality metrics for a financial exposure network.

    Parameters
    ----------
    exposure_matrix:
        Non-negative (N, N) matrix of bilateral exposures.
    metrics:
        List of metrics to compute. Defaults to ["debt_rank"].
    damping:
        Damping factor for Katz centrality.

    Returns
    -------
    dict mapping metric name to ndarray of shape (N,).
    """
    exposure_matrix = np.asarray(exposure_matrix, dtype=float)
    if exposure_matrix.ndim != 2 or exposure_matrix.shape[0] != exposure_matrix.shape[1]:
        raise ValueError("exposure_matrix must be square 2-D array")
    N = exposure_matrix.shape[0]
    if N < 2:
        raise ValueError("Need N >= 2 nodes")
    if np.any(exposure_matrix < 0):
        raise ValueError("exposure_matrix must be non-negative")

    if metrics is None:
        metrics = ["debt_rank"]

    # Build payment proportion matrix Pi
    eps = 1e-12
    row_sums = exposure_matrix.sum(axis=1, keepdims=True)
    Pi = exposure_matrix / np.maximum(row_sums, eps)

    results: dict[str, np.ndarray] = {}

    for metric in metrics:
        if metric == "debt_rank":
            # Solve (I - 0.5 * Pi^T) x = 1 for debt rank approximation
            A = np.eye(N) - 0.5 * Pi.T + eps * np.eye(N)
            try:
                dr = np.linalg.solve(A, np.ones(N))
            except np.linalg.LinAlgError:
                dr = np.ones(N)
            dr = np.abs(dr)
            dr_sum = dr.sum()
            results["debt_rank"] = dr / (dr_sum + eps)

        elif metric == "eigenvector":
            try:
                evals, evecs = np.linalg.eig(exposure_matrix.T)
                idx = np.argmax(np.abs(evals))
                evec = np.abs(evecs[:, idx].real)
            except np.linalg.LinAlgError:
                evec = np.ones(N)
            s = evec.sum()
            results["eigenvector"] = evec / (s + eps)

        elif metric == "katz":
            try:
                eig_max = float(np.max(np.abs(np.linalg.eigvals(Pi))))
            except np.linalg.LinAlgError:
                eig_max = 1.0
            A = np.eye(N) - damping * Pi.T / (eig_max + eps)
            try:
                katz = np.linalg.solve(A, np.ones(N))
            except np.linalg.LinAlgError:
                katz = np.ones(N)
            katz = np.abs(katz)
            katz /= katz.sum() + eps
            results["katz"] = katz

        elif metric == "betweenness":
            threshold = np.mean(Pi[Pi > 0]) if np.any(Pi > 0) else 0.0
            out_degree = (Pi > threshold).sum(axis=1).astype(float)
            in_degree = (Pi > threshold).sum(axis=0).astype(float)
            betw = out_degree * in_degree
            s = betw.sum()
            results["betweenness"] = betw / (s + eps)

        else:
            results[metric] = np.zeros(N)

    return results
