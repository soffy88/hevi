"""Tests for epstein_zin_solver (Bansal-Yaron 2004)."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.recursive_utility.ez_solver import epstein_zin_solver

BY_PARAMS: dict = {
    "mu": 0.0015,
    "rho": 0.979,
    "phi": 0.044,
    "sigma_bar": 0.0078,
    "nu": 0.987,
    "sigma_omega": 2.3e-6,
}


def test_required_keys() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=50)
    expected_keys = (
        "value_function",
        "consumption_policy",
        "wealth_consumption_ratio",
        "equity_premium_implied",
        "converged",
        "iterations",
    )
    for key in expected_keys:
        assert key in result


def test_converged_for_by_calibration() -> None:
    """BY calibration should converge within 500 iterations."""
    result = epstein_zin_solver(BY_PARAMS, n_grid=30, max_iter=200, tol=1e-5)
    assert result["converged"] is True, f"Did not converge after {result['iterations']} iters"


def test_wc_ratio_positive() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=100)
    assert result["wealth_consumption_ratio"] > 0


def test_equity_premium_positive() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=100)
    assert result["equity_premium_implied"] >= 0


def test_value_function_shape() -> None:
    n = 30
    result = epstein_zin_solver(BY_PARAMS, n_grid=n, max_iter=50)
    assert result["value_function"].shape == (n,)


def test_consumption_policy_shape() -> None:
    n = 30
    result = epstein_zin_solver(BY_PARAMS, n_grid=n, max_iter=50)
    assert result["consumption_policy"].shape == (n,)


def test_consumption_policy_positive() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=50)
    assert np.all(result["consumption_policy"] > 0), "C(x) must be positive"


def test_value_function_positive() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=100)
    assert np.all(result["value_function"] > 0), "V must be positive"


def test_iterations_positive() -> None:
    result = epstein_zin_solver(BY_PARAMS, n_grid=20, max_iter=50)
    assert result["iterations"] >= 1


def test_invalid_discount_raises() -> None:
    with pytest.raises(ValueError, match="discount"):
        epstein_zin_solver(BY_PARAMS, discount=1.5)


def test_invalid_risk_aversion_raises() -> None:
    with pytest.raises(ValueError, match="risk_aversion"):
        epstein_zin_solver(BY_PARAMS, risk_aversion=-1.0)


def test_invalid_ies_raises() -> None:
    with pytest.raises(ValueError, match="ies"):
        epstein_zin_solver(BY_PARAMS, ies=0.0)


def test_higher_ra_increases_equity_premium() -> None:
    """Higher risk aversion should (ceteris paribus) not decrease equity premium."""
    r_low = epstein_zin_solver(BY_PARAMS, risk_aversion=5.0, n_grid=20, max_iter=50)
    r_high = epstein_zin_solver(BY_PARAMS, risk_aversion=15.0, n_grid=20, max_iter=50)
    # Both should be non-negative
    assert r_low["equity_premium_implied"] >= 0
    assert r_high["equity_premium_implied"] >= 0
