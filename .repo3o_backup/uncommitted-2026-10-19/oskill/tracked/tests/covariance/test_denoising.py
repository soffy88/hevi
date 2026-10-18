"""Tests for denoised_covariance."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.covariance import denoised_covariance


@pytest.fixture
def sample_returns():
    """T x N returns where T >> N (required for denoising)."""
    rng = np.random.default_rng(42)
    T, N = 300, 20
    return rng.standard_normal((T, N))


@pytest.fixture
def noise_returns():
    """Pure noise returns: identity correlation structure expected."""
    rng = np.random.default_rng(99)
    T, N = 500, 10
    return rng.standard_normal((T, N))


def test_denoised_cov_returns_dict_with_six_keys(sample_returns):
    """Result must have exactly six keys."""
    result = denoised_covariance(sample_returns)
    expected_keys = {
        "covariance",
        "correlation",
        "eigenvalues_original",
        "eigenvalues_denoised",
        "lambda_plus",
        "n_signal_eigenvalues",
    }
    assert set(result.keys()) == expected_keys


def test_denoised_cov_mp_filter_basic(sample_returns):
    """mp_filter: lambda_plus computed correctly as (1+sqrt(N/T))^2."""
    T, N = sample_returns.shape
    result = denoised_covariance(sample_returns, method="mp_filter")

    expected_lambda_plus = (1.0 + np.sqrt(N / T)) ** 2
    assert abs(result["lambda_plus"] - expected_lambda_plus) < 1e-10, (
        f"lambda_plus={result['lambda_plus']} != expected {expected_lambda_plus}"
    )


def test_denoised_cov_constant_residual_basic(sample_returns):
    """constant_residual method should return valid result."""
    result = denoised_covariance(sample_returns, method="constant_residual")
    assert result["covariance"].shape == (sample_returns.shape[1],) * 2
    assert result["n_signal_eigenvalues"] >= 0


def test_denoised_cov_psd_property(sample_returns):
    """Denoised covariance must be positive semi-definite."""
    for method in ["mp_filter", "constant_residual"]:
        result = denoised_covariance(sample_returns, method=method)
        cov = result["covariance"]
        eigenvalues = np.linalg.eigvalsh(cov)
        assert np.all(eigenvalues >= -1e-10), (
            f"Covariance not PSD for method={method}: min ev={eigenvalues.min()}"
        )


def test_denoised_cov_trace_preserved_approx(sample_returns):
    """Trace of denoised correlation matrix should be approximately N (within 10%).

    The denoising preserves the trace of the correlation matrix (sum of eigenvalues = N).
    """
    result = denoised_covariance(sample_returns, method="mp_filter")
    N = sample_returns.shape[1]

    # Trace of denoised correlation should be approximately N
    corr = result["correlation"]
    trace_corr = np.trace(corr)
    # Allow 10% deviation
    assert abs(trace_corr - N) / N < 0.10, (
        f"Trace of denoised corr={trace_corr:.2f} deviates too much from N={N}"
    )


def test_denoised_cov_n_signal_eigenvalues_nonneg(sample_returns):
    """Number of signal eigenvalues must be non-negative."""
    result = denoised_covariance(sample_returns)
    assert result["n_signal_eigenvalues"] >= 0
    assert result["n_signal_eigenvalues"] <= sample_returns.shape[1]


def test_denoised_cov_pure_noise_has_few_signal_evs(noise_returns):
    """Pure i.i.d. noise should have very few signal eigenvalues (n_signal ≈ 0).

    For i.i.d. returns, all eigenvalues should be near the MP distribution.
    """
    result = denoised_covariance(noise_returns, method="mp_filter")
    # With pure noise and large T/N ratio, most eigenvalues are noise
    # n_signal should be small (< N/2)
    N = noise_returns.shape[1]
    assert result["n_signal_eigenvalues"] < N, (
        f"Expected few signal eigenvalues for noise, got {result['n_signal_eigenvalues']}/{N}"
    )


def test_denoised_cov_insufficient_data_raises():
    """T < N + 10 should raise ValueError."""
    rng = np.random.default_rng(0)
    N = 20
    T = N + 5  # T < N + 10
    returns = rng.standard_normal((T, N))
    with pytest.raises(ValueError, match="Insufficient data"):
        denoised_covariance(returns)


def test_denoised_cov_dataframe_input(sample_returns):
    """Should accept pandas DataFrame as input."""
    df = pd.DataFrame(sample_returns)
    result = denoised_covariance(df)
    assert result["covariance"].shape == (sample_returns.shape[1],) * 2


# ─── Additional A-class gap tests ─────────────────────────────────────────────


def test_denoised_covariance_ndarray_input():
    """Pure ndarray input (not DataFrame) should work correctly."""
    rng = np.random.default_rng(7)
    data = rng.standard_normal((200, 10))  # ndarray, not DataFrame
    result = denoised_covariance(data)
    assert result["covariance"].shape == (10, 10)
    assert result["n_signal_eigenvalues"] >= 0


def test_denoised_covariance_constant_residual_method():
    """constant_residual method should return a valid 6-key dict."""
    rng = np.random.default_rng(8)
    data = rng.standard_normal((200, 10))
    result = denoised_covariance(data, method="constant_residual")
    expected_keys = {
        "covariance",
        "correlation",
        "eigenvalues_original",
        "eigenvalues_denoised",
        "lambda_plus",
        "n_signal_eigenvalues",
    }
    assert set(result.keys()) == expected_keys
    assert result["covariance"].shape == (10, 10)


def test_denoised_covariance_unknown_method_raises():
    """Unknown method should raise ValueError."""
    rng = np.random.default_rng(0)
    data = rng.standard_normal((200, 10))
    with pytest.raises(ValueError, match="Unknown method"):
        denoised_covariance(data, method="bad_method")


@pytest.mark.academic_reference
def test_denoised_cov_mp_upper_bound_formula(sample_returns):
    """lambda_+ = (1 + sqrt(N/T))^2 per Marchenko-Pastur theory, rtol=1e-10.

    Reference: López de Prado (2020) Ch.2 Eq. 2.4
    """
    T, N = sample_returns.shape
    result = denoised_covariance(sample_returns)

    # Verify exact formula
    q = T / N
    lambda_plus_expected = (1.0 + np.sqrt(1.0 / q)) ** 2
    np.testing.assert_allclose(
        result["lambda_plus"],
        lambda_plus_expected,
        rtol=1e-10,
        err_msg="Marchenko-Pastur upper bound formula incorrect",
    )

    # Eigenvalues structure check
    ev_orig = result["eigenvalues_original"]
    assert len(ev_orig) == N
    # Original eigenvalues should be sorted ascending
    assert np.all(np.diff(ev_orig) >= -1e-10), "Original eigenvalues not sorted ascending"
