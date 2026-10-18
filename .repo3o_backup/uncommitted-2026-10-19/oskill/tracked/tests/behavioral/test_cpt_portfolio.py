"""Tests for CPT portfolio optimization."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.behavioral.cpt_portfolio import cpt_portfolio_optimize


@pytest.fixture
def returns_5x50():
    rng = np.random.default_rng(0)
    return rng.normal(0.001, 0.02, (50, 5))


@pytest.fixture
def returns_2x20():
    rng = np.random.default_rng(1)
    return rng.normal(0.0, 0.01, (20, 2))


def test_weights_sum_to_one(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_cpt_value_is_scalar(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert isinstance(result["cpt_value"], float)
    assert not np.isnan(result["cpt_value"])


def test_no_nan_in_weights(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert not np.any(np.isnan(result["weights"]))


def test_empirical_metrics_has_sharpe(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert "sharpe" in result["empirical_metrics"]
    assert not np.isnan(result["empirical_metrics"]["sharpe"])


def test_empirical_metrics_has_max_drawdown_and_var(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    m = result["empirical_metrics"]
    assert "max_drawdown" in m
    assert "var_95" in m
    assert m["max_drawdown"] <= 0.0


def test_weights_shape(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert result["weights"].shape == (5,)


def test_convergence_key_present(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, solver="scipy_slsqp")
    assert "convergence" in result
    assert "success" in result["convergence"]


def test_de_solver_produces_valid_weights(returns_2x20):
    result = cpt_portfolio_optimize(returns_2x20, solver="scipy_de")
    assert abs(result["weights"].sum() - 1.0) < 1e-2
    assert not np.any(np.isnan(result["weights"]))


def test_invalid_shape_raises():
    with pytest.raises(ValueError, match="2-D"):
        cpt_portfolio_optimize(np.ones(10))


def test_too_few_observations_raises():
    rng = np.random.default_rng(2)
    with pytest.raises(ValueError, match="T >= 10"):
        cpt_portfolio_optimize(rng.normal(0, 0.01, (5, 3)))


def test_too_few_assets_raises():
    rng = np.random.default_rng(3)
    with pytest.raises(ValueError, match="N >= 2"):
        cpt_portfolio_optimize(rng.normal(0, 0.01, (20, 1)))


def test_custom_reference_return(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, reference_return=0.001, solver="scipy_slsqp")
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_n_long_short_postprocessing(returns_5x50):
    result = cpt_portfolio_optimize(returns_5x50, n_long_short=(2, 1), solver="scipy_slsqp")
    w = result["weights"]
    assert abs(w.sum() - 1.0) < 1e-4
    assert not np.any(np.isnan(w))
