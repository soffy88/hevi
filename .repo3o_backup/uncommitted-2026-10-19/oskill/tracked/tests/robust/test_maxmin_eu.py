"""Tests for max-min expected utility portfolio optimization."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.robust.maxmin_eu import maxmin_expected_utility_portfolio


@pytest.fixture
def two_scenarios():
    rng = np.random.default_rng(42)
    s1 = rng.normal(0.001, 0.01, (60, 4))
    s2 = rng.normal(-0.002, 0.02, (60, 4))
    return [s1, s2]


@pytest.fixture
def three_scenarios():
    rng = np.random.default_rng(7)
    return [rng.normal(0.001 * (i + 1), 0.01, (50, 3)) for i in range(3)]


def test_weights_sum_to_one(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios)
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_weights_non_negative(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios)
    assert np.all(result["weights"] >= -1e-6)


def test_worst_case_le_all_scenarios(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios)
    wcu = result["worst_case_utility"]
    for eu in result["utilities_by_prior"]:
        assert wcu <= eu + 1e-6


def test_utilities_by_prior_length(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios)
    assert len(result["utilities_by_prior"]) == 2


def test_worst_prior_index_matches(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios)
    idx = result["worst_prior_index"]
    eus = result["utilities_by_prior"]
    assert eus[idx] == min(eus)


def test_log_utility(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios, utility="log")
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_power_utility(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios, utility="power", risk_aversion=3.0)
    assert abs(result["weights"].sum() - 1.0) < 1e-4
    assert not np.any(np.isnan(result["weights"]))


def test_exponential_utility(two_scenarios):
    result = maxmin_expected_utility_portfolio(
        two_scenarios, utility="exponential", risk_aversion=1.0
    )
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_alpha_maxmin(two_scenarios):
    result = maxmin_expected_utility_portfolio(two_scenarios, method="alpha_maxmin", alpha=0.7)
    assert abs(result["weights"].sum() - 1.0) < 1e-4
    assert not np.any(np.isnan(result["weights"]))


def test_three_scenarios(three_scenarios):
    result = maxmin_expected_utility_portfolio(three_scenarios)
    assert len(result["utilities_by_prior"]) == 3
    assert abs(result["weights"].sum() - 1.0) < 1e-4


def test_too_few_scenarios_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="at least 2"):
        maxmin_expected_utility_portfolio([rng.normal(0, 0.01, (30, 3))])


def test_mismatched_n_raises():
    rng = np.random.default_rng(0)
    s1 = rng.normal(0, 0.01, (30, 3))
    s2 = rng.normal(0, 0.01, (30, 4))
    with pytest.raises(ValueError, match="assets"):
        maxmin_expected_utility_portfolio([s1, s2])
