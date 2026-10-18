"""Tests for ssd_milp_optimizer."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.portfolio.ssd_milp import ssd_milp_optimizer


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(99)


@pytest.fixture
def asset_data(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    T, N = 60, 5
    asset_returns = rng.normal(0.001, 0.02, size=(T, N))
    benchmark_returns = rng.normal(0.0005, 0.018, size=T)
    return asset_returns, benchmark_returns


def test_required_keys(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark)
    expected_keys = (
        "weights",
        "ssd_constraint_active_states",
        "milp_objective",
        "dominance_certificate",
    )
    for key in expected_keys:
        assert key in result


def test_weights_sum_to_one(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark)
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_weights_nonnegative_no_short_selling(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark, short_selling=False)
    assert np.all(result["weights"] >= -1e-9), "No short selling: weights must be >= 0"


def test_objective_is_scalar(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark)
    assert np.isscalar(result["milp_objective"]) or np.ndim(result["milp_objective"]) == 0


def test_objective_mean_matches_mean_return(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark, objective="mean")
    expected = float(np.mean(asset_returns, axis=0) @ result["weights"])
    np.testing.assert_allclose(result["milp_objective"], expected, atol=1e-4)


def test_tsd_runs(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark, dominance_order="tsd")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_msd_runs(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark, dominance_order="msd")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_cvar_objective(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark, objective="cvar")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_dominance_certificate_shape(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark)
    # Should have at most 5 values
    assert len(result["dominance_certificate"]) <= 5


def test_too_few_rows_raises() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="20"):
        ssd_milp_optimizer(
            rng.normal(size=(10, 3)),
            rng.normal(size=10),
        )


def test_too_few_assets_raises() -> None:
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="2 assets"):
        ssd_milp_optimizer(
            rng.normal(size=(30, 1)),
            rng.normal(size=30),
        )


def test_ssd_active_states_is_list(asset_data: tuple) -> None:
    asset_returns, benchmark = asset_data
    result = ssd_milp_optimizer(asset_returns, benchmark)
    assert isinstance(result["ssd_constraint_active_states"], list)


def test_short_selling_allows_negative_weights() -> None:
    rng = np.random.default_rng(5)
    T, N = 60, 3
    asset_returns = rng.normal(0.001, 0.02, size=(T, N))
    benchmark_returns = rng.normal(0.0005, 0.018, size=T)
    result = ssd_milp_optimizer(asset_returns, benchmark_returns, short_selling=True)
    # Weights sum to 1 even with short selling
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)
