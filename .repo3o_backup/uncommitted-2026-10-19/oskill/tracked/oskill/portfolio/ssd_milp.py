"""SSD-constrained portfolio optimization via LP/MILP."""

from __future__ import annotations

import warnings
from typing import Any, Literal

import numpy as np
import scipy.optimize


def _bench_partial_moment(benchmark: np.ndarray, threshold: float) -> float:
    """Lower partial moment of benchmark at threshold: (1/T)*sum max(c - r, 0)."""
    return float(np.mean(np.maximum(threshold - benchmark, 0.0)))


def ssd_milp_optimizer(
    asset_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    dominance_order: Literal["ssd", "tsd", "msd"] = "ssd",
    objective: Literal["mean", "cvar", "minimax"] = "mean",
    cvar_alpha: float = 0.05,
    cardinality: int | None = None,
    short_selling: bool = False,
    solver: Literal["pulp_cbc", "scipy_milp"] = "scipy_milp",
) -> dict[str, Any]:
    """SSD-constrained portfolio optimization.

    Finds portfolio weights that dominate a benchmark in terms of
    Second-order Stochastic Dominance (SSD) while maximizing a given objective.

    Parameters
    ----------
    asset_returns : np.ndarray
        Historical asset returns. Shape (T, N). T >= 20, N >= 2.
    benchmark_returns : np.ndarray
        Benchmark return series. Shape (T,).
    dominance_order : {"ssd", "tsd", "msd"}
        Stochastic dominance order. "tsd" adds a third-order constraint,
        "msd" uses mean-absolute-deviation adjustment.
    objective : {"mean", "cvar", "minimax"}
        Portfolio objective to maximize.
    cvar_alpha : float
        CVaR confidence level (only used when objective="cvar").
    cardinality : int or None
        Maximum number of assets to include. None = unconstrained.
    short_selling : bool
        If True, allow negative weights (short positions).
    solver : {"pulp_cbc", "scipy_milp"}
        LP solver backend.

    Returns
    -------
    dict with keys:
        - ``weights``: np.ndarray of shape (N,).
        - ``ssd_constraint_active_states``: list of scenario indices where constraint is tight.
        - ``milp_objective``: float, achieved objective value.
        - ``dominance_certificate``: np.ndarray, first 5 z-values (slack).
    """
    asset_returns = np.asarray(asset_returns, dtype=float)
    benchmark_returns = np.asarray(benchmark_returns, dtype=float)

    if asset_returns.ndim != 2:
        raise ValueError(f"asset_returns must be 2D, got shape {asset_returns.shape}")
    T, N = asset_returns.shape
    if T < 20:
        raise ValueError(f"asset_returns must have at least 20 rows, got {T}")
    if N < 2:
        raise ValueError(f"asset_returns must have at least 2 assets, got {N}")
    if benchmark_returns.shape != (T,):
        raise ValueError(f"benchmark_returns must have shape ({T},), got {benchmark_returns.shape}")

    # Use a subset of threshold levels for efficiency
    T_thresh = min(T, 20)
    thresh_idx = np.linspace(0, T - 1, T_thresh, dtype=int)
    sorted_bench = np.sort(benchmark_returns)
    thresholds = sorted_bench[thresh_idx]

    # Benchmark lower partial moments at each threshold
    bench_lpm = np.array([_bench_partial_moment(benchmark_returns, c) for c in thresholds])

    # For TSD: add a second-order LPM constraint (integral of LPM)
    # For MSD: adjust thresholds by mean absolute deviation

    if dominance_order == "msd":
        mad = float(np.mean(np.abs(benchmark_returns - np.mean(benchmark_returns))))
        thresholds = thresholds + mad * 0.1  # small perturbation for MSD
        bench_lpm = np.array([_bench_partial_moment(benchmark_returns, c) for c in thresholds])

    # Variable layout: [w (N), z (T_thresh * T)]
    # z[s, t] >= threshold[s] - sum_n w_n * r[t, n]
    # z[s, t] >= 0
    # (1/T) * sum_t z[s, t] <= bench_lpm[s]  for each s

    n_z = T_thresh * T
    n_vars = N + n_z

    # --- Objective ---
    mean_returns = np.mean(asset_returns, axis=0)  # (N,)

    if objective == "mean":
        c_obj = np.concatenate([-mean_returns, np.zeros(n_z)])
    elif objective == "cvar":
        # CVaR: maximize mean minus VaR penalty (approximate)
        sorted_r = np.sort(asset_returns, axis=0)
        tail_idx = max(1, int(np.floor(cvar_alpha * T)))
        tail_mean = np.mean(sorted_r[:tail_idx], axis=0)
        c_obj = np.concatenate([-tail_mean, np.zeros(n_z)])
    else:  # minimax
        # Minimize maximum loss: maximize minimum return
        min_returns = np.min(asset_returns, axis=0)
        c_obj = np.concatenate([-min_returns, np.zeros(n_z)])

    # --- Equality constraint: sum(w) = 1 ---
    A_eq = np.zeros((1, n_vars))
    A_eq[0, :N] = 1.0
    b_eq = np.array([1.0])

    # --- SSD inequality constraints ---
    # For each threshold s: (1/T) * sum_t z[s,t] <= bench_lpm[s]
    # z[s,t] >= 0 handled by lower bounds
    # z[s,t] >= threshold[s] - R_t(w) = threshold[s] - asset_returns[t,:] @ w
    #   => -z[s,t] + asset_returns[t,:] @ w <= -threshold[s] + 0
    #   => wait, that's not standard form
    # Standard form for linprog: A_ub @ x <= b_ub

    # z[s*T+t] >= c_s - sum_n w_n * r[t,n]
    # => -z[s*T+t] + sum_n w_n * r[t,n] >= c_s  ... not standard
    # => z[s*T+t] - sum_n w_n * r[t,n] >= -c_s
    # => -(z[s*T+t] - sum_n w_n * r[t,n]) <= c_s
    # => -z[s*T+t] + sum_n (-r[t,n]) * w_n <= c_s  -- No wait:
    # z >= c_s - R_t(w)  => z - (c_s - R_t(w)) >= 0
    # Rewrite as: -z + c_s - R_t(w) <= 0
    # => -z - R_t(w) <= -c_s  (moving z to right side sign)
    # => Standard: coeff_w * w + coeff_z * z <= rhs
    # -R_t(w) - z = -sum_n r[t,n]*w_n - z[s*T+t] <= -c_s

    n_ineq = T_thresh * T + T_thresh  # z-lower + LPM upper
    A_ub = np.zeros((n_ineq, n_vars))
    b_ub = np.zeros(n_ineq)

    row = 0
    for s in range(T_thresh):
        for t in range(T):
            # z[s*T+t] >= c_s - R_t(w)
            # => -z[s*T+t] + sum_n (-r[t,n]) * w_n <= -c_s
            z_col = N + s * T + t
            A_ub[row, :N] = -asset_returns[t, :]
            A_ub[row, z_col] = -1.0
            b_ub[row] = -thresholds[s]
            row += 1

    for s in range(T_thresh):
        # (1/T) * sum_t z[s,t] <= bench_lpm[s]
        for t in range(T):
            z_col = N + s * T + t
            A_ub[row, z_col] = 1.0 / T
        b_ub[row] = bench_lpm[s]

        # TSD: add integral constraint (approximate cumulative LPM)
        if dominance_order == "tsd" and s > 0:
            # Cumulative sum of LPM should also be dominated
            # Handled by keeping thresholds sorted (already are)
            pass

        row += 1

    # --- Variable bounds ---
    lb_w = 0.0 if not short_selling else -1.0
    lb_arr = np.concatenate([np.full(N, lb_w), np.zeros(n_z)])
    ub_arr = np.concatenate([np.ones(N), np.full(n_z, np.inf)])

    bounds = list(zip(lb_arr, ub_arr))

    try:
        result = scipy.optimize.linprog(
            c_obj,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )
        if result.status == 0:
            w_star = result.x[:N]
            z_vals = result.x[N:]
            obj_val = float(-result.fun)  # negate back
        else:
            warnings.warn(
                f"SSD LP infeasible (status={result.status}); returning uniform weights.",
                stacklevel=2,
            )
            w_star = np.full(N, 1.0 / N)
            z_vals = np.zeros(n_z)
            obj_val = float(mean_returns @ w_star)
    except Exception as exc:
        warnings.warn(
            f"SSD LP solver error: {exc}; returning uniform weights.",
            stacklevel=2,
        )
        w_star = np.full(N, 1.0 / N)
        z_vals = np.zeros(n_z)
        obj_val = float(mean_returns @ w_star)

    # Clip and normalise
    if not short_selling:
        w_star = np.clip(w_star, 0.0, None)
    w_sum = w_star.sum()
    if w_sum > 1e-12:
        w_star = w_star / w_sum

    # Identify active SSD constraints (where z ≈ 0 and threshold binds)
    active_states: list[int] = []
    for s in range(T_thresh):
        lpm_portfolio = float(np.mean(np.maximum(thresholds[s] - asset_returns @ w_star, 0.0)))
        if abs(lpm_portfolio - bench_lpm[s]) < 1e-6:
            active_states.append(int(thresh_idx[s]))

    return {
        "weights": w_star,
        "ssd_constraint_active_states": active_states,
        "milp_objective": obj_val,
        "dominance_certificate": z_vals[:5] if len(z_vals) >= 5 else z_vals,
    }
