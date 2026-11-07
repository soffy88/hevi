"""Tests for posterior_diagnostics."""

from __future__ import annotations

import numpy as np

from oskill.bayesian.posterior_diagnostics import posterior_diagnostics

EXPECTED_KEYS = {
    "r_hat",
    "effective_sample_size",
    "autocorrelation",
    "mean",
    "std",
    "credible_intervals",
    "converged",
}


def test_pd_basic_array_input():
    rng = np.random.default_rng(42)
    samples = rng.standard_normal(500)
    result = posterior_diagnostics(samples)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert isinstance(result["mean"], float)
    assert isinstance(result["std"], float)


def test_pd_single_chain_r_hat_is_one():
    rng = np.random.default_rng(42)
    samples = rng.standard_normal(200)
    result = posterior_diagnostics(samples, n_chains=1)
    assert result["r_hat"] == 1.0


def test_pd_ess_positive():
    rng = np.random.default_rng(42)
    samples = rng.standard_normal(300)
    result = posterior_diagnostics(samples)
    assert result["effective_sample_size"] > 0.0


def test_pd_ess_less_than_n_for_autocorrelated():
    # Highly autocorrelated chain: AR(1) with phi=0.99
    rng = np.random.default_rng(42)
    n = 500
    chain = np.zeros(n)
    chain[0] = rng.standard_normal()
    for t in range(1, n):
        chain[t] = 0.99 * chain[t - 1] + 0.1 * rng.standard_normal()
    result = posterior_diagnostics(chain, n_chains=1)
    # ESS should be much less than N for a strongly autocorrelated chain
    assert result["effective_sample_size"] < n * 0.5


def test_pd_dict_input():
    rng = np.random.default_rng(42)
    samples_dict = {
        "alpha": rng.standard_normal(300),
        "beta": rng.standard_normal(300),
    }
    result = posterior_diagnostics(samples_dict)
    assert isinstance(result["r_hat"], dict)
    assert "alpha" in result["r_hat"]
    assert "beta" in result["r_hat"]
    assert isinstance(result["mean"], dict)


def test_pd_credible_intervals_bounds():
    rng = np.random.default_rng(42)
    samples = rng.standard_normal(500)
    result = posterior_diagnostics(samples)
    ci = result["credible_intervals"]
    mean = result["mean"]
    assert ci["95%"]["lower"] < mean < ci["95%"]["upper"]
    assert ci["50%"]["lower"] < mean < ci["50%"]["upper"]


def test_pd_converged_flag_good_chain():
    rng = np.random.default_rng(42)
    # IID samples should converge
    samples = rng.standard_normal(600)
    result = posterior_diagnostics(samples, n_chains=1)
    # For a single chain R-hat=1.0 and ESS > N/2, so should be converged
    assert result["converged"] is True


def test_pd_2d_array_multiparams():
    rng = np.random.default_rng(42)
    P = 3
    samples = rng.standard_normal((400, P))
    result = posterior_diagnostics(samples)
    # Results should be dicts keyed by column index string
    assert isinstance(result["r_hat"], dict)
    assert len(result["r_hat"]) == P
    assert "0" in result["r_hat"]
    assert "2" in result["r_hat"]
    assert isinstance(result["mean"], dict)
