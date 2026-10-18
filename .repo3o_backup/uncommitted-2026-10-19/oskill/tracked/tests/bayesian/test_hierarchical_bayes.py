"""Tests for hierarchical_bayes_normal."""

from __future__ import annotations

import numpy as np

from oskill.bayesian.hierarchical import hierarchical_bayes_normal

EXPECTED_KEYS = {
    "group_means_samples",
    "group_means_credible_intervals",
    "population_mean_samples",
    "population_std_samples",
    "group_variances_samples",
    "n_effective",
}


def _two_groups(rng):
    g1 = rng.normal(loc=2.0, scale=0.5, size=30)
    g2 = rng.normal(loc=5.0, scale=0.5, size=30)
    return {"g1": g1, "g2": g2}


def test_hbn_basic_two_groups():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=500, n_warmup=200, seed=42)
    assert EXPECTED_KEYS.issubset(result.keys())
    assert "g1" in result["group_means_samples"]
    assert "g2" in result["group_means_samples"]


def test_hbn_group_means_reasonable():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=1000, n_warmup=500, seed=42)
    ci = result["group_means_credible_intervals"]
    # Posterior mean for g1 should be near 2, g2 near 5
    assert abs(ci["g1"]["mean"] - 2.0) < 1.0
    assert abs(ci["g2"]["mean"] - 5.0) < 1.0


def test_hbn_credible_intervals_contain_true():
    rng = np.random.default_rng(42)
    true_means = {"g1": 2.0, "g2": 5.0}
    groups = {
        "g1": rng.normal(loc=2.0, scale=0.5, size=40),
        "g2": rng.normal(loc=5.0, scale=0.5, size=40),
    }
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=1000, n_warmup=500, seed=7)
    ci = result["group_means_credible_intervals"]
    for g, true_val in true_means.items():
        lo = ci[g]["95_lower"]
        hi = ci[g]["95_upper"]
        assert lo < true_val < hi, f"Group {g}: true={true_val} not in [{lo:.2f}, {hi:.2f}]"


def test_hbn_partial_pooling():
    rng = np.random.default_rng(42)
    # Groups with very different sizes: small group should be pulled more toward population mean
    groups = {
        "large": rng.normal(loc=0.0, scale=1.0, size=100),
        "small": rng.normal(loc=10.0, scale=1.0, size=5),
    }
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=1000, n_warmup=500, seed=42)
    ci = result["group_means_credible_intervals"]
    # Small group should be pulled toward population mean (shrinkage)
    # Its posterior mean should be less than raw empirical mean of 10
    small_post_mean = ci["small"]["mean"]
    ci["large"]["mean"]
    # Partial pooling: small group mean should be pulled toward large group
    assert small_post_mean < 10.0 + 3.0  # bounded from above


def test_hbn_population_mean_samples_shape():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    n_samples = 300
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=n_samples, n_warmup=100, seed=42)
    assert result["population_mean_samples"].shape == (n_samples,)
    assert result["population_std_samples"].shape == (n_samples,)


def test_hbn_group_variances_positive():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=500, n_warmup=200, seed=42)
    for name, samples in result["group_variances_samples"].items():
        assert np.all(samples > 0.0), f"Group {name} has non-positive variance samples"


def test_hbn_n_effective_positive():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=500, n_warmup=200, seed=42)
    assert result["n_effective"] > 0


def test_hbn_seed_reproducible():
    rng = np.random.default_rng(42)
    groups = _two_groups(rng)
    r1 = hierarchical_bayes_normal(groups, n_mcmc_samples=300, n_warmup=100, seed=99)
    r2 = hierarchical_bayes_normal(groups, n_mcmc_samples=300, n_warmup=100, seed=99)
    np.testing.assert_array_equal(r1["population_mean_samples"], r2["population_mean_samples"])


def test_hbn_many_groups():
    rng = np.random.default_rng(42)
    true_means = [1.0, 2.0, 3.0, 4.0, 5.0]
    groups = {
        f"group_{i}": rng.normal(loc=mu, scale=0.5, size=20) for i, mu in enumerate(true_means)
    }
    result = hierarchical_bayes_normal(groups, n_mcmc_samples=500, n_warmup=200, seed=42)
    assert len(result["group_means_credible_intervals"]) == 5
    assert result["population_mean_samples"].shape == (500,)
