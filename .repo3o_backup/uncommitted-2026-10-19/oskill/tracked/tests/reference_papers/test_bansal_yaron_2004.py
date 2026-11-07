"""Reference paper reproduction tests: Epstein-Zin / Bansal-Yaron (2004).

Reference
---------
Bansal, R. & Yaron, A. (2004). Risks for the long run: A potential resolution of
    asset pricing puzzles. Journal of Finance, 59(4), 1481-1509.

Tests verify that the epstein_zin_solver correctly implements:
- Convergence of the value-function iteration
- Reasonable wealth-consumption ratios
- Positive implied equity premium consistent with BY calibration
"""

from __future__ import annotations

import numpy as np
import pytest

from oskill.recursive_utility.ez_solver import epstein_zin_solver

# ---------------------------------------------------------------------------
# Bansal-Yaron (2004) Table I monthly calibration (annualised μ ≈ 1.8%)
# ---------------------------------------------------------------------------
BY_PROCESS = {
    "mu": 0.0015,  # mean consumption growth (monthly)
    "rho": 0.979,  # long-run risk persistence
    "phi": 0.044,  # long-run risk loading
    "sigma_bar": 0.0078,  # mean conditional volatility
    "nu": 0.987,  # variance persistence
    "sigma_omega": 2.3e-6,
}


@pytest.mark.academic_reference
def test_returns_dict_with_required_keys():
    """Solver must return a dict containing all documented keys."""
    result = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=10.0, ies=1.5)
    assert isinstance(result, dict), "Expected dict return type."
    required_keys = {
        "value_function",
        "consumption_policy",
        "wealth_consumption_ratio",
        "equity_premium_implied",
        "converged",
        "iterations",
    }
    for key in required_keys:
        assert key in result, f"Missing key: {key}"


@pytest.mark.academic_reference
def test_value_function_finite_and_positive():
    """Value function must be finite and positive everywhere on the grid."""
    result = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=10.0, ies=1.5)
    vf = result["value_function"]
    assert np.all(np.isfinite(vf)), "Value function contains non-finite values."
    assert np.all(vf > 0), "Value function must be positive."


@pytest.mark.academic_reference
def test_converged_under_standard_calibration():
    """Solver must converge under the standard BY calibration."""
    result = epstein_zin_solver(
        BY_PROCESS,
        discount=0.99,
        risk_aversion=10.0,
        ies=1.5,
        max_iter=500,
        tol=1e-6,
    )
    assert result["converged"], f"Solver did not converge after {result['iterations']} iterations."


@pytest.mark.academic_reference
def test_positive_equity_premium_with_by_params():
    """Implied equity premium must be positive with gamma > 1/psi (BY condition)."""
    # gamma=10 > 1/ies=1/1.5≈0.67, so equity premium should be positive
    result = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=10.0, ies=1.5)
    ep = result["equity_premium_implied"]
    assert np.isfinite(ep), "Equity premium must be finite."
    assert ep >= 0.0, f"Expected non-negative equity premium with gamma>1/psi, got {ep}"


@pytest.mark.academic_reference
def test_wealth_consumption_ratio_reasonable():
    """Wealth-consumption ratio must be a positive finite number."""
    result = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=10.0, ies=1.5)
    wc = result["wealth_consumption_ratio"]
    assert np.isfinite(wc), "Wealth-consumption ratio must be finite."
    assert wc > 0, "Wealth-consumption ratio must be positive."


@pytest.mark.academic_reference
def test_consumption_policy_grid_matches_n_grid():
    """Consumption policy array must match n_grid length."""
    n_grid = 80
    result = epstein_zin_solver(BY_PROCESS, n_grid=n_grid)
    assert len(result["consumption_policy"]) == n_grid
    assert len(result["value_function"]) == n_grid


@pytest.mark.academic_reference
def test_higher_risk_aversion_raises_equity_premium():
    """Increasing gamma raises implied equity premium (standard EZ comparative static)."""
    r_low = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=5.0, ies=1.5)
    r_high = epstein_zin_solver(BY_PROCESS, discount=0.99, risk_aversion=15.0, ies=1.5)
    ep_low = r_low["equity_premium_implied"]
    ep_high = r_high["equity_premium_implied"]
    assert ep_high >= ep_low, (
        f"Higher risk aversion should raise equity premium: {ep_low} vs {ep_high}"
    )


@pytest.mark.academic_reference
def test_invalid_discount_raises():
    """discount outside (0, 1) must raise ValueError."""
    with pytest.raises(ValueError, match="discount"):
        epstein_zin_solver(BY_PROCESS, discount=1.5)


@pytest.mark.academic_reference
def test_invalid_risk_aversion_raises():
    """Non-positive risk_aversion must raise ValueError."""
    with pytest.raises(ValueError, match="risk_aversion"):
        epstein_zin_solver(BY_PROCESS, risk_aversion=-1.0)


@pytest.mark.academic_reference
def test_invalid_ies_raises():
    """Non-positive ies must raise ValueError."""
    with pytest.raises(ValueError, match="ies"):
        epstein_zin_solver(BY_PROCESS, ies=0.0)


@pytest.mark.academic_reference
def test_iterations_count_positive():
    """Iteration count must be at least 1."""
    result = epstein_zin_solver(BY_PROCESS)
    assert result["iterations"] >= 1
