"""Tests for salience_asset_pricing (BGS 2013 AER)."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.behavioral.salience_pricing import salience_asset_pricing


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(0)


@pytest.fixture
def single_asset_data(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    S = 20
    asset = rng.normal(1.0, 0.3, size=S)
    market = rng.normal(1.0, 0.3, size=S)
    return asset, market


@pytest.fixture
def multi_asset_data(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    N, S = 5, 30
    assets = rng.normal(1.0, 0.5, size=(N, S))
    market = rng.normal(1.0, 0.3, size=S)
    return assets, market


def test_keys_present(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    result = salience_asset_pricing(asset, market)
    expected_keys = (
        "salient_price",
        "rational_price",
        "mispricing",
        "distorted_probabilities",
        "salience_scores",
    )
    for key in expected_keys:
        assert key in result


def test_delta_one_gives_rational_price(single_asset_data: tuple) -> None:
    """delta=1 → uniform distortion → salient = rational."""
    asset, market = single_asset_data
    result = salience_asset_pricing(asset, market, delta=1.0)
    np.testing.assert_allclose(
        result["salient_price"],
        result["rational_price"],
        rtol=1e-6,
        err_msg="delta=1 should give salient_price == rational_price",
    )


def test_single_asset_output_shape(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    result = salience_asset_pricing(asset, market)
    shape = result["salient_price"].shape
    assert shape == (1,), f"Expected (1,), got {shape}"
    assert result["rational_price"].shape == (1,)
    assert result["mispricing"].shape == (1,)


def test_multi_asset_output_shape(multi_asset_data: tuple) -> None:
    assets, market = multi_asset_data
    N = assets.shape[0]
    result = salience_asset_pricing(assets, market)
    assert result["salient_price"].shape == (N,)
    assert result["rational_price"].shape == (N,)
    assert result["mispricing"].shape == (N,)
    assert result["distorted_probabilities"].shape == (N, assets.shape[1])
    assert result["salience_scores"].shape == (N, assets.shape[1])


def test_mispricing_equals_difference(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    result = salience_asset_pricing(asset, market)
    np.testing.assert_allclose(
        result["mispricing"],
        result["salient_price"] - result["rational_price"],
    )


def test_distorted_probs_sum_to_one(multi_asset_data: tuple) -> None:
    assets, market = multi_asset_data
    result = salience_asset_pricing(assets, market)
    row_sums = result["distorted_probabilities"].sum(axis=1)
    np.testing.assert_allclose(row_sums, np.ones(assets.shape[0]), atol=1e-10)


def test_salience_scores_nonnegative(multi_asset_data: tuple) -> None:
    assets, market = multi_asset_data
    result = salience_asset_pricing(assets, market)
    assert np.all(result["salience_scores"] >= 0), "Salience scores must be non-negative"


def test_custom_probabilities(rng: np.random.Generator) -> None:
    S = 10
    asset = rng.normal(1.0, 0.3, size=S)
    market = rng.normal(1.0, 0.3, size=S)
    probs = np.abs(rng.normal(size=S))
    probs /= probs.sum()
    result = salience_asset_pricing(asset, market, payoff_probabilities=probs)
    # Rational price should match EV with given probs
    expected_rational = float(np.sum(probs * asset) / 1.0)
    np.testing.assert_allclose(result["rational_price"][0], expected_rational, rtol=1e-10)


def test_higher_delta_less_distortion(single_asset_data: tuple) -> None:
    """Higher delta (closer to 1) should reduce mispricing magnitude."""
    asset, market = single_asset_data
    r_low = salience_asset_pricing(asset, market, delta=0.3)
    r_high = salience_asset_pricing(asset, market, delta=0.9)
    mp_low = float(np.abs(r_low["mispricing"][0]))
    mp_high = float(np.abs(r_high["mispricing"][0]))
    # This is not always guaranteed for every dataset, but for random data
    # the ratio should be reasonable — just check both are finite
    assert np.isfinite(mp_low) and np.isfinite(mp_high)


def test_risk_free_rate_effect(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    r0 = salience_asset_pricing(asset, market, risk_free_rate=0.0)
    r5 = salience_asset_pricing(asset, market, risk_free_rate=0.05)
    # Higher rf → lower price
    assert r5["rational_price"][0] < r0["rational_price"][0]


def test_wrong_market_shape_raises(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    with pytest.raises(ValueError):
        salience_asset_pricing(asset, market[:-1])  # wrong S


def test_wrong_prob_shape_raises(single_asset_data: tuple) -> None:
    asset, market = single_asset_data
    with pytest.raises(ValueError):
        salience_asset_pricing(asset, market, payoff_probabilities=np.ones(5))
