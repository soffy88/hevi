"""Tests for oskill.hmm.gaussian_hmm."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.hmm import gaussian_hmm

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def bimodal_series():
    """200 points drawn from two well-separated Gaussians."""
    rng = np.random.default_rng(42)
    cluster0 = rng.normal(-3, 0.5, 100)
    cluster1 = rng.normal(3, 0.5, 100)
    return np.concatenate([cluster0, cluster1])


@pytest.fixture
def helivex_series():
    """60 observations, three-state pattern (Helivex usage pattern)."""
    rng = np.random.default_rng(42)
    part0 = rng.normal(-2, 0.4, 20)
    part1 = rng.normal(0, 0.4, 20)
    part2 = rng.normal(2, 0.4, 20)
    return np.concatenate([part0, part1, part2])


# ─── basic API ───────────────────────────────────────────────────────────────


def test_gaussian_hmm_returns_correct_keys(bimodal_series):
    """Result must contain exactly the documented keys."""
    result = gaussian_hmm(bimodal_series, n_states=2, random_state=0)
    expected = {
        "means",
        "stds",
        "transition_matrix",
        "state_probs",
        "viterbi_path",
        "log_likelihood",
        "converged",
    }
    assert set(result.keys()) == expected


def test_gaussian_hmm_two_state_output_shapes(bimodal_series):
    """200 points, n_states=2 → state_probs.shape=(200,2), viterbi_path.shape=(200,)."""
    result = gaussian_hmm(bimodal_series, n_states=2, random_state=0)
    assert result["state_probs"].shape == (200, 2)
    assert result["viterbi_path"].shape == (200,)


def test_gaussian_hmm_state_probs_sum_to_one(bimodal_series):
    """Each row of state_probs sums to ≈ 1."""
    result = gaussian_hmm(bimodal_series, n_states=2, random_state=0)
    row_sums = result["state_probs"].sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-6)


def test_gaussian_hmm_viterbi_path_valid_states(bimodal_series):
    """All viterbi_path values must be in [0, n_states)."""
    n_states = 2
    result = gaussian_hmm(bimodal_series, n_states=n_states, random_state=0)
    path = result["viterbi_path"]
    assert int(path.min()) >= 0
    assert int(path.max()) < n_states


def test_gaussian_hmm_three_state_convergence():
    """Bimodal + flat mix → n_states=3 runs without error (converged may be True or False)."""
    rng = np.random.default_rng(7)
    x = np.concatenate(
        [
            rng.normal(-3, 0.5, 80),
            rng.normal(0, 0.3, 40),
            rng.normal(3, 0.5, 80),
        ]
    )
    result = gaussian_hmm(x, n_states=3, n_iter=50, random_state=7)
    assert result["viterbi_path"].shape == (200,)
    assert isinstance(result["converged"], bool)


def test_gaussian_hmm_two_clusters_distinguish_means():
    """x = [0]*100 + [5]*100, n_states=2 → two distinct means."""
    x = np.concatenate([np.zeros(100), np.full(100, 5.0)])
    result = gaussian_hmm(x, n_states=2, n_iter=100, random_state=0)
    means = sorted(result["means"])
    # The two discovered means should be on opposite sides of 2.5
    assert means[0] < 2.5
    assert means[1] > 2.5


def test_gaussian_hmm_minimum_data_runs():
    """Very short series (20 points) still returns a valid dict."""
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, 20)
    result = gaussian_hmm(x, n_states=2, random_state=1)
    assert "viterbi_path" in result
    assert len(result["viterbi_path"]) == 20


def test_gaussian_hmm_random_state_determinism():
    """Same random_state → identical viterbi_path."""
    rng = np.random.default_rng(55)
    x = rng.normal(0, 1, 100)
    r1 = gaussian_hmm(x, n_states=2, random_state=42)
    r2 = gaussian_hmm(x, n_states=2, random_state=42)
    np.testing.assert_array_equal(r1["viterbi_path"], r2["viterbi_path"])


def test_gaussian_hmm_helivex_pattern(helivex_series):
    """3 states, random_state=42, len=60 → valid shapes and prob rows sum to 1."""
    result = gaussian_hmm(helivex_series, n_states=3, random_state=42)
    assert result["state_probs"].shape == (60, 3)
    assert result["viterbi_path"].shape == (60,)
    row_sums = result["state_probs"].sum(axis=1)
    np.testing.assert_allclose(row_sums, 1.0, atol=1e-5)


@pytest.mark.academic_reference
def test_gaussian_hmm_baum_welch_1970():
    """Baum et al. (1970): EM log-likelihood must be non-decreasing.

    Run with n_iter=1 vs n_iter=50 on the same data; verify
    log_likelihood(50) >= log_likelihood(1) - numerical tolerance.

    Reference: Baum, L.E. et al. (1970). Annals of Mathematical Statistics.
    """
    rng = np.random.default_rng(99)
    x = np.concatenate([rng.normal(-2, 0.5, 100), rng.normal(2, 0.5, 100)])

    r1 = gaussian_hmm(x, n_states=2, n_iter=1, tol=-1e9, random_state=0)
    r50 = gaussian_hmm(x, n_states=2, n_iter=50, tol=-1e9, random_state=0)

    # EM should not decrease log-likelihood over more iterations
    assert r50["log_likelihood"] >= r1["log_likelihood"] - 1e-4, (
        f"EM log-likelihood decreased: iter1={r1['log_likelihood']:.4f} "
        f"> iter50={r50['log_likelihood']:.4f}"
    )
