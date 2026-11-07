"""§11.2 Solver convergence tests for oskill solvers.

Parametrized over 20 seeds to keep CI fast while covering diverse random inputs.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from oskill.behavioral.cpt_portfolio import cpt_portfolio_optimize
from oskill.networks.clearing import eisenberg_noe_clearing
from oskill.portfolio.ssd_milp import ssd_milp_optimizer
from oskill.recursive_utility.ez_solver import epstein_zin_solver

SEEDS = list(range(20))

# ---------------------------------------------------------------------------
# 1. CPT portfolio optimizer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_cpt_portfolio_optimize_convergence(seed: int) -> None:
    """cpt_portfolio_optimize must return a dict with a 'weights' key for any seed."""
    rng = np.random.default_rng(seed)
    returns = rng.standard_normal((252, 5)) * 0.01

    result = cpt_portfolio_optimize(returns, solver="scipy_slsqp")

    assert isinstance(result, dict), "Result must be a dict"
    assert "weights" in result, "Result must contain 'weights' key"
    weights = result["weights"]
    assert weights is not None, "Weights must not be None"
    assert len(weights) == 5, "Weights length must match number of assets"
    assert all(math.isfinite(float(w)) for w in weights), "All weights must be finite"


# ---------------------------------------------------------------------------
# 2. Eisenberg-Noe clearing
# ---------------------------------------------------------------------------


def _random_liability_matrix(rng: np.random.Generator, n: int = 4) -> np.ndarray:
    """Build a non-negative upper-triangular liability matrix with zero diagonal."""
    L = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            L[i, j] = rng.uniform(0.0, 1.0)
    return L


@pytest.mark.parametrize("seed", SEEDS)
def test_eisenberg_noe_clearing_convergence(seed: int) -> None:
    """eisenberg_noe_clearing must not raise and return a non-negative clearing vector."""
    rng = np.random.default_rng(seed)
    liabilities = _random_liability_matrix(rng, n=4)
    external_assets = rng.uniform(0.0, 2.0, size=4)

    result = eisenberg_noe_clearing(liabilities, external_assets)

    assert isinstance(result, dict), "Result must be a dict"
    assert "clearing_vector" in result, "Result must contain 'clearing_vector'"
    cv = result["clearing_vector"]
    assert np.sum(cv) >= 0.0, "Sum of clearing vector must be >= 0"
    assert all(math.isfinite(float(v)) for v in cv), "All clearing values must be finite"


# ---------------------------------------------------------------------------
# 3. SSD MILP optimizer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_ssd_milp_optimizer_convergence(seed: int) -> None:
    """ssd_milp_optimizer must return a dict with 'weights' key for any seed."""
    rng = np.random.default_rng(seed)
    # Generate asset returns (T=120, N=4) and a benchmark (T=120)
    asset_returns = rng.standard_normal((120, 4)) * 0.01
    # Use first asset column as benchmark
    benchmark_returns = rng.standard_normal(120) * 0.01

    result = ssd_milp_optimizer(asset_returns, benchmark_returns)

    assert isinstance(result, dict), "Result must be a dict"
    assert "weights" in result, "Result must contain 'weights' key"
    weights = result["weights"]
    assert len(weights) == 4, "Weights length must match number of assets"
    assert all(math.isfinite(float(w)) for w in weights), "All weights must be finite"


# ---------------------------------------------------------------------------
# 4. Epstein-Zin recursive utility solver
# ---------------------------------------------------------------------------

_BY_PROCESS = {
    "mu": 0.0015,
    "rho": 0.979,
    "phi": 0.044,
    "sigma_bar": 0.0078,
    "nu": 0.987,
    "sigma_omega": 2.3e-6,
}


@pytest.mark.parametrize("seed", SEEDS)
def test_epstein_zin_solver_convergence(seed: int) -> None:
    """epstein_zin_solver must return a dict with finite value function entries."""
    rng = np.random.default_rng(seed)

    # Perturb process parameters slightly per seed for variety
    process = {
        "mu": 0.0015 + rng.uniform(-0.0005, 0.0005),
        "rho": float(np.clip(0.979 + rng.uniform(-0.01, 0.01), 0.0, 0.999)),
        "phi": float(np.clip(0.044 + rng.uniform(-0.005, 0.005), 0.001, 0.1)),
        "sigma_bar": float(np.clip(0.0078 + rng.uniform(-0.001, 0.001), 0.001, 0.05)),
        "nu": float(np.clip(0.987 + rng.uniform(-0.01, 0.01), 0.0, 0.999)),
        "sigma_omega": 2.3e-6,
    }

    result = epstein_zin_solver(
        process,
        discount=0.99,
        risk_aversion=10.0,
        ies=1.5,
        max_iter=200,
        tol=1e-5,
    )

    assert isinstance(result, dict), "Result must be a dict"
    assert "value_function" in result, "Result must contain 'value_function'"
    vf = result["value_function"]
    assert len(vf) > 0, "Value function must be non-empty"
    assert all(math.isfinite(float(v)) for v in vf), "All value function entries must be finite"
    assert "converged" in result, "Result must contain 'converged' key"
    assert "iterations" in result, "Result must contain 'iterations' key"
    assert result["iterations"] > 0, "Solver must have performed at least one iteration"
