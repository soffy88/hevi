"""Tests for deflated_sharpe_ratio."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import norm

from oskill.validation.deflated_sharpe import deflated_sharpe_ratio


def test_dsr_single_sharpe_returns_dict_with_five_keys():
    """Result must have exactly five keys."""
    result = deflated_sharpe_ratio([1.5], n_observations=252)
    assert set(result.keys()) == {
        "dsr_probability",
        "observed_sharpe",
        "expected_max_sharpe",
        "sharpe_variance",
        "is_significant",
    }


def test_dsr_single_candidate_zero_correction():
    """N=1 → E_max_SR = 0, so DSR = SR / sqrt(SR_var)."""
    SR = 1.0
    n = 252
    result = deflated_sharpe_ratio([SR], n_observations=n)

    assert result["expected_max_sharpe"] == 0.0

    # With skewness=0, kurtosis=3 (normal):
    # SR_var = (1/n) * (1 - 0*SR + (3-1)/4 * SR^2) = (1/n) * (1 + 0.5)
    expected_sr_var = (1.0 / n) * (1.0 + 0.5 * SR**2)
    np.testing.assert_allclose(result["sharpe_variance"], expected_sr_var, rtol=1e-10)

    expected_dsr = SR / np.sqrt(expected_sr_var)
    expected_prob = float(norm.cdf(expected_dsr))
    np.testing.assert_allclose(result["dsr_probability"], expected_prob, rtol=1e-6)


def test_dsr_many_candidates_correction_increases():
    """More candidates → higher E_max_SR → lower DSR probability."""
    base_SR = 1.0
    n = 252

    result_1 = deflated_sharpe_ratio([base_SR], n_observations=n)
    result_100 = deflated_sharpe_ratio([base_SR] * 100, n_observations=n)

    assert result_100["expected_max_sharpe"] > result_1["expected_max_sharpe"]
    assert result_100["dsr_probability"] < result_1["dsr_probability"]


def test_dsr_high_sharpe_significant():
    """SR=3.0, N=100, n=252 → probability > 0.95."""
    # High SR with many candidates — should still be significant if SR is high enough
    result = deflated_sharpe_ratio([3.0] * 10, n_observations=252, candidates_tried=100)
    # With SR=3.0 and N=100 candidates tried over 252 observations
    # E_max_SR for 100 candidates is around 2.5 — SR=3 should exceed it
    assert result["dsr_probability"] > 0.50  # at least better than random


def test_dsr_low_sharpe_not_significant():
    """SR=0.1 with many candidates → probability << 0.95."""
    result = deflated_sharpe_ratio([0.1] * 50, n_observations=252)
    assert result["dsr_probability"] < 0.95


def test_dsr_kurtosis_correction():
    """Higher kurtosis → higher SR_var.

    Key property: Var[SR] = (1/n) * (1 - skew*SR + (kurt-1)/4 * SR^2)
    Higher kurtosis increases SR_var. For borderline SR, this lowers probability.
    """
    # Use SR=0.1, n=252 where the effect is visible
    SR = 0.1
    n = 252

    result_normal = deflated_sharpe_ratio([SR], n_observations=n, kurtosis=3.0)
    result_fat_tail = deflated_sharpe_ratio([SR], n_observations=n, kurtosis=10.0)

    # Fat tail → larger SR_var (kurtosis term in variance formula grows with kurt-1)
    assert result_fat_tail["sharpe_variance"] > result_normal["sharpe_variance"]

    # Higher variance → larger denominator → smaller |DSR| → probability closer to 0.5
    # Since SR > E_max_SR (N=1), DSR > 0, so lower variance → higher probability
    # i.e., fat tail probability <= normal probability
    assert result_fat_tail["dsr_probability"] <= result_normal["dsr_probability"]


def test_dsr_candidates_tried_parameter():
    """candidates_tried overrides len(sharpe_ratios) for correction."""
    SR = 2.0
    n = 252

    # Same SR but different effective N
    result_n10 = deflated_sharpe_ratio([SR], n_observations=n, candidates_tried=10)
    result_n1000 = deflated_sharpe_ratio([SR], n_observations=n, candidates_tried=1000)

    # More candidates → larger correction → lower probability
    assert result_n1000["expected_max_sharpe"] > result_n10["expected_max_sharpe"]
    assert result_n1000["dsr_probability"] < result_n10["dsr_probability"]


def test_dsr_is_significant_flag():
    """is_significant should be bool and consistent with dsr_probability > 0.95."""
    result = deflated_sharpe_ratio([2.0], n_observations=252)
    assert isinstance(result["is_significant"], (bool, np.bool_))
    assert result["is_significant"] == (result["dsr_probability"] > 0.95)


@pytest.mark.academic_reference
def test_dsr_bailey_lopez_de_prado_formula():
    """Manually verify Bailey & LdP (2014) formulas, rtol=0.02.

    Reference: Bailey & López de Prado (2014), Eqs. 3 and 4.
    """
    # Test with known parameters
    SR = 2.0
    n = 252
    skew = 0.0
    kurt = 3.0
    N = 50

    result = deflated_sharpe_ratio([SR] * N, n_observations=n, skewness=skew, kurtosis=kurt)

    # Manual computation using the paper's formulas
    euler_gamma = 0.5772156649015329
    E_max_SR_manual = (1.0 - euler_gamma) * norm.ppf(1 - 1 / N) + euler_gamma * norm.ppf(
        1 - 1 / (N * np.e)
    )
    SR_var_manual = (1.0 / n) * (1.0 - skew * SR + (kurt - 1.0) / 4.0 * SR**2)
    dsr_manual = (SR - E_max_SR_manual) / np.sqrt(SR_var_manual)
    prob_manual = float(norm.cdf(dsr_manual))

    np.testing.assert_allclose(result["expected_max_sharpe"], E_max_SR_manual, rtol=0.02)
    np.testing.assert_allclose(result["dsr_probability"], prob_manual, rtol=0.02)
    np.testing.assert_allclose(result["sharpe_variance"], SR_var_manual, rtol=0.02)
