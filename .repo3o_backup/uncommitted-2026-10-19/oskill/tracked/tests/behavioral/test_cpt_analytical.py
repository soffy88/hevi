"""Tests for cpt_portfolio_analytical (Bernard-Ghossoub 2010)."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.behavioral.cpt_analytical import cpt_portfolio_analytical


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def sample_returns(rng: np.random.Generator) -> np.ndarray:
    return rng.normal(0.001, 0.02, size=100)


def test_returns_required_keys(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.0)
    expected_keys = (
        "weight_optimal",
        "cpt_value",
        "llad",
        "well_posed",
        "comparative_statics",
        "closed_form_used",
    )
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"


def test_weight_optimal_is_finite(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.001)
    assert np.isfinite(result["weight_optimal"]), "weight_optimal must be finite"


def test_weight_optimal_in_bounds(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.001)
    w = result["weight_optimal"]
    assert -3.0 <= w <= 3.0, f"weight_optimal {w} out of bounds [-3, 3]"


def test_llad_greater_than_one_for_tk_params(sample_returns: np.ndarray) -> None:
    """TK default params: alpha=beta=0.88, loss_aversion=2.25 → LLAD > 1."""
    result = cpt_portfolio_analytical(
        sample_returns,
        reference_return=0.0,
        alpha=0.88,
        beta=0.88,
        loss_aversion=2.25,
    )
    assert result["llad"] > 1.0, f"LLAD should be > 1 for TK params, got {result['llad']}"


def test_well_posed_is_valid(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.0)
    assert result["well_posed"] in (None, True, False), "well_posed should be None, True, or False"


def test_closed_form_for_piecewise_linear(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.0, case="piecewise_linear")
    assert result["closed_form_used"] is True


def test_auto_case_with_alpha_beta_one_uses_closed_form(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(
        sample_returns, reference_return=0.0, alpha=1.0, beta=1.0, loss_aversion=1.0
    )
    assert result["closed_form_used"] is True


def test_auto_case_with_nonunit_params_uses_numerical(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(
        sample_returns,
        reference_return=0.0,
        alpha=0.88,
        beta=0.88,
        case="auto",
    )
    assert result["closed_form_used"] is False


def test_comparative_statics_structure(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.001)
    cs = result["comparative_statics"]
    assert isinstance(cs, dict)
    for param in ("alpha", "beta", "loss_aversion"):
        assert param in cs, f"Missing param in comparative_statics: {param}"
        assert "plus_10pct" in cs[param]
        assert "minus_10pct" in cs[param]


def test_too_few_samples_raises() -> None:
    with pytest.raises(ValueError, match="30"):
        cpt_portfolio_analytical(np.random.randn(20), reference_return=0.0)


def test_cpt_value_is_finite(sample_returns: np.ndarray) -> None:
    result = cpt_portfolio_analytical(sample_returns, reference_return=0.0)
    assert np.isfinite(result["cpt_value"]), "cpt_value must be finite"


def test_2d_returns_accepted(rng: np.random.Generator) -> None:
    returns_2d = rng.normal(0.001, 0.02, size=(60, 1))
    result = cpt_portfolio_analytical(returns_2d, reference_return=0.0)
    assert np.isfinite(result["weight_optimal"])


def test_different_reference_returns_give_different_weights(sample_returns: np.ndarray) -> None:
    r1 = cpt_portfolio_analytical(sample_returns, reference_return=-0.01)["weight_optimal"]
    r2 = cpt_portfolio_analytical(sample_returns, reference_return=0.01)["weight_optimal"]
    assert r1 != r2, "Different reference returns should yield different weights"
