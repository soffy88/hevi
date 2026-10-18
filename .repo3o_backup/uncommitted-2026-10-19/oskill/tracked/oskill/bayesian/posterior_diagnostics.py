"""Posterior diagnostics: R-hat, ESS, autocorrelation, and convergence checks."""

from __future__ import annotations

from typing import Any

import numpy as np


def _autocorrelation(x: np.ndarray, max_lag: int) -> np.ndarray:
    """Compute normalised autocorrelation for lags 1..max_lag."""
    n = len(x)
    xc = x - x.mean()
    var = np.var(xc)
    if var < 1e-14:
        return np.zeros(max_lag)
    full = np.correlate(xc, xc, mode="full")
    acf = full[n - 1 :] / (var * n)
    return acf[1 : max_lag + 1]


def _ess(x: np.ndarray) -> float:
    """Effective sample size from truncated autocorrelation sum."""
    n = len(x)
    max_lag = min(n // 4, 100)
    rho = _autocorrelation(x, max_lag)
    cumsum = 0.0
    for r in rho:
        if r <= 0:
            break
        cumsum += r
    return float(n / (1.0 + 2.0 * cumsum))


def _rhat(x: np.ndarray, n_chains: int) -> float:
    """Compute Gelman-Rubin R-hat by splitting x into n_chains segments."""
    if n_chains < 2:
        return 1.0
    n_total = len(x)
    chain_len = n_total // n_chains
    chains = [x[i * chain_len : (i + 1) * chain_len] for i in range(n_chains)]
    chain_means = np.array([c.mean() for c in chains])
    chain_vars = np.array([np.var(c, ddof=1) if len(c) > 1 else 0.0 for c in chains])
    W = float(chain_vars.mean())
    float(chain_means.mean())
    B = float(chain_len * np.var(chain_means, ddof=1)) if n_chains > 1 else 0.0
    if W < 1e-14:
        return 1.0
    var_hat = (chain_len - 1) / chain_len * W + B / chain_len
    return float(np.sqrt(var_hat / W))


def _diagnostics_1d(x: np.ndarray, n_chains: int) -> dict[str, Any]:
    """Compute diagnostics for a single 1-D chain."""
    n = len(x)
    max_lag = min(n // 4, 100)
    acf = _autocorrelation(x, max_lag)
    ess = _ess(x)
    rhat = _rhat(x, n_chains)
    mean_val = float(x.mean())
    std_val = float(x.std(ddof=1))
    ci_50_lo, ci_50_hi = float(np.percentile(x, 25)), float(np.percentile(x, 75))
    ci_95_lo, ci_95_hi = float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))
    converged = bool(rhat < 1.05 and ess > n / 2.0)

    return {
        "r_hat": rhat,
        "effective_sample_size": ess,
        "autocorrelation": acf,
        "mean": mean_val,
        "std": std_val,
        "credible_intervals": {
            "50%": {"lower": ci_50_lo, "upper": ci_50_hi},
            "95%": {"lower": ci_95_lo, "upper": ci_95_hi},
        },
        "converged": converged,
    }


def posterior_diagnostics(
    posterior_samples: np.ndarray | dict[str, np.ndarray],
    *,
    n_chains: int = 1,
) -> dict[str, Any]:
    """Compute posterior diagnostics including R-hat, ESS, autocorrelation.

    Args:
        posterior_samples: 1-D array (N,), 2-D array (N, P), or dict of 1-D arrays.
            When n_chains > 1 with array input, the array is split into n_chains
            equal segments to compute R-hat.
        n_chains: Number of chains for R-hat computation.

    Returns:
        Dict with r_hat, effective_sample_size, autocorrelation, mean, std,
        credible_intervals, converged.  For multi-param input each value is a
        sub-dict keyed by parameter name / column index.

    Reference:
        Gelman & Rubin (1992).
    """
    if isinstance(posterior_samples, dict):
        keys = list(posterior_samples.keys())
        per_param = {
            k: _diagnostics_1d(np.asarray(v, dtype=np.float64), n_chains)
            for k, v in posterior_samples.items()
        }
        return {
            "r_hat": {k: per_param[k]["r_hat"] for k in keys},
            "effective_sample_size": {k: per_param[k]["effective_sample_size"] for k in keys},
            "autocorrelation": {k: per_param[k]["autocorrelation"] for k in keys},
            "mean": {k: per_param[k]["mean"] for k in keys},
            "std": {k: per_param[k]["std"] for k in keys},
            "credible_intervals": {k: per_param[k]["credible_intervals"] for k in keys},
            "converged": all(per_param[k]["converged"] for k in keys),
        }

    arr = np.asarray(posterior_samples, dtype=np.float64)

    if arr.ndim == 1:
        return _diagnostics_1d(arr, n_chains)

    # 2-D: (N, P) — compute per column
    N, P = arr.shape
    per_col = {str(j): _diagnostics_1d(arr[:, j], n_chains) for j in range(P)}
    return {
        "r_hat": {k: per_col[k]["r_hat"] for k in per_col},
        "effective_sample_size": {k: per_col[k]["effective_sample_size"] for k in per_col},
        "autocorrelation": {k: per_col[k]["autocorrelation"] for k in per_col},
        "mean": {k: per_col[k]["mean"] for k in per_col},
        "std": {k: per_col[k]["std"] for k in per_col},
        "credible_intervals": {k: per_col[k]["credible_intervals"] for k in per_col},
        "converged": all(per_col[k]["converged"] for k in per_col),
    }
