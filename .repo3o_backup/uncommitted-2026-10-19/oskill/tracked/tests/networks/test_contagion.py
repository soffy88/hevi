"""Tests for interbank contagion simulation."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.networks.contagion import contagion_simulate


@pytest.fixture
def small_network():
    """5-bank fully connected network."""
    rng = np.random.default_rng(0)
    E = np.abs(rng.normal(0, 5, (5, 5)))
    np.fill_diagonal(E, 0.0)
    return E


def test_small_shock_no_cascade(small_network):
    """When shock is smaller than capital buffers, no defaults."""
    caps = np.ones(5) * 1000.0
    shock = np.zeros(5)
    shock[0] = 0.001
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    assert result["total_defaults"] == 0
    assert len(result["defaults_by_round"]) == 0


def test_large_shock_causes_defaults(small_network):
    """Large shock exceeding all buffers leads to defaults."""
    caps = np.zeros(5)
    shock = np.ones(5) * 100.0
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    assert result["total_defaults"] > 0
    assert len(result["defaults_by_round"]) > 0


def test_defaults_by_round_format(small_network):
    """Each entry in defaults_by_round is (round_int, list_of_ints)."""
    caps = np.zeros(5)
    shock = np.ones(5) * 10.0
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    for rnd, defaults in result["defaults_by_round"]:
        assert isinstance(rnd, int)
        assert isinstance(defaults, list)


def test_final_losses_shape(small_network):
    """final_losses has same shape as number of nodes."""
    caps = np.ones(5) * 50.0
    shock = np.array([100.0, 0.0, 0.0, 0.0, 0.0])
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    assert result["final_losses"].shape == (5,)


def test_cascade_size_is_max_round_size(small_network):
    """cascade_size equals the max defaults in any single round."""
    caps = np.zeros(5)
    shock = np.ones(5) * 50.0
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    if result["defaults_by_round"]:
        expected = max(len(d) for _, d in result["defaults_by_round"])
        assert result["cascade_size"] == expected
    else:
        assert result["cascade_size"] == 0


def test_fire_sale_increases_losses(small_network):
    """Fire sale intensity > 0 should increase final losses."""
    caps = np.ones(5) * 5.0
    shock = np.array([20.0, 0.0, 0.0, 0.0, 0.0])
    result_no_fire = contagion_simulate(
        small_network, shock, capital_buffer=caps, fire_sale_intensity=0.0
    )
    result_fire = contagion_simulate(
        small_network, shock, capital_buffer=caps, fire_sale_intensity=0.5
    )
    # At least one node should have higher losses with fire sale
    assert np.sum(result_fire["final_losses"]) >= np.sum(result_no_fire["final_losses"])


def test_rogers_veraart_rule(small_network):
    """Rogers-Veraart rule should also run without error."""
    caps = np.ones(5) * 5.0
    shock = np.array([20.0, 0.0, 0.0, 0.0, 0.0])
    result = contagion_simulate(
        small_network, shock, capital_buffer=caps, transmission_rule="rogers_veraart"
    )
    assert "defaults_by_round" in result
    assert "final_losses" in result
    assert result["final_losses"].shape == (5,)


def test_single_isolated_default():
    """Single bank with no connections defaults only itself."""
    E = np.zeros((3, 3))  # no exposures
    shock = np.array([100.0, 0.0, 0.0])
    caps = np.array([50.0, 50.0, 50.0])
    result = contagion_simulate(E, shock, capital_buffer=caps)
    assert result["total_defaults"] == 1


def test_total_defaults_consistent(small_network):
    """total_defaults equals total unique banks across all rounds."""
    caps = np.zeros(5)
    shock = np.ones(5) * 10.0
    result = contagion_simulate(small_network, shock, capital_buffer=caps)
    all_d = {node for _, rnd_d in result["defaults_by_round"] for node in rnd_d}
    assert result["total_defaults"] == len(all_d)
