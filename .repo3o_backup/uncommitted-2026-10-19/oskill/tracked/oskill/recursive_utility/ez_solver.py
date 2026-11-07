"""Epstein-Zin recursive utility solver (Bansal-Yaron 2004 calibration)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np

try:
    from oprim.recursive_utility.epstein_zin import epstein_zin_aggregator
except ImportError:

    def epstein_zin_aggregator(  # type: ignore[misc]
        consumption: np.ndarray,
        continuation_value: np.ndarray,
        *,
        discount: float,
        risk_aversion: float,
        ies: float,
    ) -> np.ndarray:
        rho = 1.0 - 1.0 / ies
        consumption = np.asarray(consumption, dtype=float)
        continuation_value = np.asarray(continuation_value, dtype=float)
        if abs(rho) < 1e-12:
            return consumption ** (1.0 - discount) * continuation_value**discount
        inner = (1.0 - discount) * consumption**rho + discount * continuation_value**rho
        return inner ** (1.0 / rho)


def _gauss_hermite_nodes_weights(n: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """Gauss-Hermite quadrature nodes and weights for integral of f(x)*exp(-x^2)."""
    nodes, weights = np.polynomial.hermite.hermgauss(n)
    return nodes, weights


def epstein_zin_solver(
    consumption_process: dict[str, Any],
    *,
    discount: float = 0.998,
    risk_aversion: float = 10.0,
    ies: float = 1.5,
    n_grid: int = 100,
    max_iter: int = 500,
    tol: float = 1e-6,
    method: Literal["fixed_point", "policy_iteration"] = "fixed_point",
) -> dict[str, Any]:
    """Epstein-Zin recursive utility solver (Bansal-Yaron 2004).

    Solves the value function for the Epstein-Zin / Kreps-Porteus recursive
    utility model with long-run risks (Bansal-Yaron 2004, JF).

    Parameters
    ----------
    consumption_process : dict
        Monthly calibration parameters:
        - ``mu``: mean consumption growth (0.0015)
        - ``rho``: long-run risk persistence (0.979)
        - ``phi``: long-run risk volatility loading (0.044)
        - ``sigma_bar``: mean volatility (0.0078)
        - ``nu``: volatility persistence (0.987)
        - ``sigma_omega``: volatility-of-volatility (2.3e-6)
    discount : float
        Time discount factor beta. Must be in (0, 1).
    risk_aversion : float
        Relative risk aversion gamma. Must be > 0.
    ies : float
        Intertemporal elasticity of substitution psi. Must be > 0.
    n_grid : int
        Number of grid points for the x (long-run risk) state.
    max_iter : int
        Maximum fixed-point iterations.
    tol : float
        Convergence tolerance (sup-norm on value function).
    method : {"fixed_point", "policy_iteration"}
        Solution method ("policy_iteration" maps to same fixed-point here).

    Returns
    -------
    dict with keys:
        - ``value_function``: np.ndarray of shape (n_grid,), V on the x-grid.
        - ``consumption_policy``: np.ndarray of shape (n_grid,), C(x) on grid.
        - ``wealth_consumption_ratio``: float, WC ratio at the mean state.
        - ``equity_premium_implied``: float, approximate equity premium (BY eq.).
        - ``converged``: bool, whether the iteration converged.
        - ``iterations``: int, number of iterations performed.
    """
    if not (0.0 < discount < 1.0):
        raise ValueError(f"discount must be in (0, 1), got {discount!r}")
    if risk_aversion <= 0.0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion!r}")
    if ies <= 0.0:
        raise ValueError(f"ies must be > 0, got {ies!r}")

    # --- Unpack process parameters ---
    mu = float(consumption_process.get("mu", 0.0015))
    rho = float(consumption_process.get("rho", 0.979))
    phi = float(consumption_process.get("phi", 0.044))
    sigma_bar = float(consumption_process.get("sigma_bar", 0.0078))
    nu = float(consumption_process.get("nu", 0.987))  # noqa: F841
    sigma_omega = float(consumption_process.get("sigma_omega", 2.3e-6))  # noqa: F841

    gamma = risk_aversion

    # --- Build 1D grid for x at fixed sigma = sigma_bar ---
    sigma_x = phi * sigma_bar / np.sqrt(max(1.0 - rho**2, 1e-10))
    x_grid = np.linspace(-3.0 * sigma_x, 3.0 * sigma_x, n_grid)

    # Gauss-Hermite nodes for next-period shocks (10-point)
    n_quad = 10
    gh_nodes, gh_weights = _gauss_hermite_nodes_weights(n_quad)

    # Normalize weights (GH is for integral of f*exp(-z^2), convert to standard normal)
    # For E[f(z)] where z ~ N(0,1): use nodes/sqrt(2), weights/sqrt(pi)
    z_nodes = gh_nodes * np.sqrt(2.0)  # standard-normal quadrature nodes
    z_weights = gh_weights / np.sqrt(np.pi)  # normalized weights sum to 1

    # --- Initialize value function ---
    # Use a simple initial guess: V proportional to consumption
    V = np.ones(n_grid)

    # Consumption at each x: C(x) = exp(mu + x) (normalized, C_base = 1)
    C_grid = np.exp(mu + x_grid)

    converged = False
    n_iter = 0

    for iteration in range(max_iter):
        V_new = np.empty(n_grid)

        for i in range(n_grid):
            x_i = x_grid[i]

            # Next-period x: x' = rho*x_i + phi*sigma_bar*epsilon, epsilon ~ N(0,1)
            x_next = rho * x_i + phi * sigma_bar * z_nodes  # shape (n_quad,)

            # Interpolate V at next-period states
            V_next = np.interp(x_next, x_grid, V)  # shape (n_quad,)

            # Certainty equivalent: CE = (sum_k weights_k * V_next_k^(1-gamma))^(1/(1-gamma))
            if abs(gamma - 1.0) < 1e-8:
                # Log case
                log_ce = float(np.sum(z_weights * np.log(np.maximum(V_next, 1e-10))))
                ce = float(np.exp(log_ce))
            else:
                exp = 1.0 - gamma
                ce_raw = float(np.sum(z_weights * np.maximum(V_next, 1e-10) ** exp))
                ce = float(np.maximum(ce_raw, 1e-30) ** (1.0 / exp))

            # Epstein-Zin aggregation
            C_i = C_grid[i]
            v_new_i = epstein_zin_aggregator(
                np.array([C_i]),
                continuation_value=np.array([max(ce, 1e-30)]),
                discount=discount,
                risk_aversion=gamma,
                ies=ies,
            )
            V_new[i] = float(v_new_i[0])

        # Ensure positivity
        V_new = np.maximum(V_new, 1e-30)

        # Check convergence (relative sup-norm for better numerical behavior)
        change = float(np.max(np.abs(V_new - V) / np.maximum(np.abs(V), 1e-10)))
        V = V_new
        n_iter = iteration + 1

        if change < tol:
            converged = True
            break

    # --- Wealth-consumption ratio at mean state (x=0) ---
    x_mean_idx = int(np.argmin(np.abs(x_grid)))
    wc_ratio = float(V[x_mean_idx] / max(C_grid[x_mean_idx], 1e-30))

    # --- Implied equity premium (Bansal-Yaron Table I approximation) ---
    # ep ≈ (gamma - 1/ies) * phi^2 * sigma_bar^2 / (1 - rho^2) * (approx)
    var_x = (phi * sigma_bar) ** 2 / max(1.0 - rho**2, 1e-10)
    ep = float((gamma - 1.0 / ies) * var_x * 12.0)  # annualize monthly
    # Ensure positive equity premium (standard for BY calibration with gamma > 1/ies)
    ep = max(ep, 0.0)

    return {
        "value_function": V,
        "consumption_policy": C_grid,
        "wealth_consumption_ratio": wc_ratio,
        "equity_premium_implied": ep,
        "converged": converged,
        "iterations": n_iter,
    }
