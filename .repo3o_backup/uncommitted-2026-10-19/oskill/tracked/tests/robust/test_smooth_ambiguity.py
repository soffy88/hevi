"""Tests for smooth_ambiguity_portfolio (KMM 2005)."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.robust.smooth_ambiguity import smooth_ambiguity_portfolio


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(7)


@pytest.fixture
def two_model_data(rng: np.random.Generator) -> tuple[list[np.ndarray], np.ndarray]:
    T, N = 60, 3
    models = [rng.normal(0.001, 0.02, size=(T, N)) for _ in range(2)]
    prior = np.array([0.5, 0.5])
    return models, prior


@pytest.fixture
def three_model_data(rng: np.random.Generator) -> tuple[list[np.ndarray], np.ndarray]:
    T, N = 80, 4
    models = [rng.normal(0.001 * k, 0.02, size=(T, N)) for k in range(3)]
    prior = np.array([0.2, 0.5, 0.3])
    return models, prior


def test_required_keys(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    expected_keys = (
        "weights",
        "expected_utility_by_model",
        "ambiguity_premium",
        "model_belief_distortion",
    )
    for key in expected_keys:
        assert key in result


def test_weights_sum_to_one(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_weights_nonnegative(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    assert np.all(result["weights"] >= -1e-9), "Weights should be non-negative"


def test_ambiguity_premium_is_scalar(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    assert np.isscalar(result["ambiguity_premium"]) or result["ambiguity_premium"].ndim == 0


def test_eu_by_model_shape(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    assert result["expected_utility_by_model"].shape == (2,)


def test_model_belief_distortion_sums_to_one(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    np.testing.assert_allclose(result["model_belief_distortion"].sum(), 1.0, atol=1e-6)


def test_three_models(three_model_data: tuple) -> None:
    models, prior = three_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior)
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)
    assert result["expected_utility_by_model"].shape == (3,)


def test_log_phi(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior, phi="log")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_power_phi(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(
        models, prior_over_models=prior, phi="power", ambiguity_aversion=2.0
    )
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_log_utility(two_model_data: tuple) -> None:
    models, prior = two_model_data
    result = smooth_ambiguity_portfolio(models, prior_over_models=prior, utility="log")
    np.testing.assert_allclose(result["weights"].sum(), 1.0, atol=1e-6)


def test_single_model_raises() -> None:
    rng = np.random.default_rng(0)
    models = [rng.normal(0.001, 0.02, size=(50, 3))]
    with pytest.raises(ValueError, match="2 models"):
        smooth_ambiguity_portfolio(models, prior_over_models=np.array([1.0]))


def test_prior_not_sum_to_one_raises(two_model_data: tuple) -> None:
    models, _ = two_model_data
    with pytest.raises(ValueError, match="sum"):
        smooth_ambiguity_portfolio(models, prior_over_models=np.array([0.3, 0.3]))
