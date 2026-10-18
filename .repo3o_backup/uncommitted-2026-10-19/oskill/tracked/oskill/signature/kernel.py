"""Signature kernel computation for path-valued data."""

from __future__ import annotations

import warnings

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


def _fallback_sig_kernel(path_a: np.ndarray, path_b: np.ndarray, depth: int) -> float:
    """Signature kernel via direct truncated signature inner product (fallback)."""
    sig_a = _compute_sig(path_a, depth)
    sig_b = _compute_sig(path_b, depth)
    return float(np.dot(sig_a, sig_b))


def _goursat_pde_kernel(path_a: np.ndarray, path_b: np.ndarray) -> float:
    """Signature kernel via Goursat PDE on [0,T]x[0,T].

    K(s,t) satisfies: d^2K/dsdt = <dx_s, dy_t> * K(s,t), K(s,0) = K(0,t) = 1.
    Solved numerically on the discrete path grid.
    """
    n_a = path_a.shape[0]
    n_b = path_b.shape[0]

    inc_a = np.diff(path_a, axis=0)  # (n_a-1, d)
    inc_b = np.diff(path_b, axis=0)  # (n_b-1, d)

    K = np.ones((n_a, n_b))
    for s in range(1, n_a):
        for t in range(1, n_b):
            ip = np.dot(inc_a[s - 1], inc_b[t - 1])
            K[s, t] = K[s - 1, t] + K[s, t - 1] - K[s - 1, t - 1] + ip * K[s - 1, t - 1]

    return float(K[-1, -1])


def signature_kernel(
    path_a: np.ndarray,
    path_b: np.ndarray,
    *,
    truncation_depth: int = 4,
    method: str = "truncated_inner_product",
    augment_with_time: bool = True,
) -> float:
    """Compute the signature kernel between two paths.

    Parameters
    ----------
    path_a:
        Array of shape (T_a, d) representing the first path.
    path_b:
        Array of shape (T_b, d) representing the second path.
    truncation_depth:
        Truncation level for the tensor-series signature expansion.
    method:
        ``"truncated_inner_product"`` — inner product of truncated signatures.
        ``"pde_solver"`` — Goursat PDE-based exact kernel.
    augment_with_time:
        If True, prepend a time channel (0, 1/T, ..., 1) before computing
        the truncated-inner-product kernel (ignored for pde_solver).

    Returns
    -------
    float
        The signature kernel value k(path_a, path_b).
    """
    path_a = np.asarray(path_a, dtype=float)
    path_b = np.asarray(path_b, dtype=float)

    if path_a.ndim != 2 or path_b.ndim != 2:
        raise ValueError("path_a and path_b must be 2-D arrays of shape (T, d).")

    if path_a.shape[1] != path_b.shape[1]:
        raise ValueError(
            f"path_a and path_b must have the same number of dimensions (d). "
            f"Got {path_a.shape[1]} vs {path_b.shape[1]}."
        )

    if method == "pde_solver":
        return _goursat_pde_kernel(path_a, path_b)
    elif method == "truncated_inner_product":
        if _HAS_SIGNATURE:
            sig_a = path_signature_compute(
                path_a, truncation_depth=truncation_depth, augment_with_time=augment_with_time
            )["signature"]
            sig_b = path_signature_compute(
                path_b, truncation_depth=truncation_depth, augment_with_time=augment_with_time
            )["signature"]
            return float(np.dot(sig_a, sig_b))
        else:
            warnings.warn(
                "oprim.signature.compute not available; using fallback truncated signature kernel.",
                ImportWarning,
                stacklevel=2,
            )
            return _fallback_sig_kernel(path_a, path_b, truncation_depth)
    else:
        raise ValueError(
            f"Unknown method: {method!r}. "
            "Valid options are 'truncated_inner_product', 'pde_solver'."
        )
