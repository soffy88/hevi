"""Tests for oskill.generative.ddpm_paths.ddpm_synthetic_path_generator."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.generative.ddpm_paths import ddpm_synthetic_path_generator


def _make_hist_returns(n=252, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(-0.0002, 0.01, n)


# ─── API / return keys ────────────────────────────────────────────────────────


def test_returns_expected_keys():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, n_synthetic_paths=10, path_length=20)
    expected = {
        "synthetic_paths",
        "noise_schedule",
        "gbm_aware_used",
        "stylized_facts_evaluation",
        "wasserstein_to_historical",
        "fingerprint",
        "denoiser_required",
    }
    assert expected == set(result.keys())


def test_synthetic_paths_shape():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, n_synthetic_paths=15, path_length=30)
    assert result["synthetic_paths"].shape == (15, 30)


def test_denoiser_required_always_true():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, n_synthetic_paths=5, path_length=10)
    assert result["denoiser_required"] is True


def test_gbm_aware_used_true():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, n_synthetic_paths=5, path_length=10)
    assert result["gbm_aware_used"] is True


def test_noise_schedule_keys():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(
        hist, n_synthetic_paths=5, path_length=10, n_diffusion_steps=50
    )
    ns = result["noise_schedule"]
    assert "betas" in ns and "alphas" in ns and "alpha_bar" in ns
    assert ns["betas"].shape == (50,)
    assert ns["alphas"].shape == (50,)
    assert ns["alpha_bar"].shape == (50,)


def test_betas_linear_schedule():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(
        hist, 5, 10, n_diffusion_steps=100, beta_schedule="linear", beta_start=1e-4, beta_end=0.02
    )
    betas = result["noise_schedule"]["betas"]
    assert abs(betas[0] - 1e-4) < 1e-6
    assert abs(betas[-1] - 0.02) < 1e-6
    # Monotone increasing
    assert np.all(np.diff(betas) >= 0)


def test_cosine_schedule():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(
        hist, 5, 10, n_diffusion_steps=50, beta_schedule="cosine"
    )
    betas = result["noise_schedule"]["betas"]
    assert np.all(betas >= 0) and np.all(betas <= 1)


def test_reproducibility_with_seed():
    hist = _make_hist_returns()
    r1 = ddpm_synthetic_path_generator(hist, 10, 20, seed=7)
    r2 = ddpm_synthetic_path_generator(hist, 10, 20, seed=7)
    np.testing.assert_array_equal(r1["synthetic_paths"], r2["synthetic_paths"])


def test_fingerprint_hex64():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, 5, 10)
    fp = result["fingerprint"]
    assert isinstance(fp, str) and len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_wasserstein_non_negative():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, 10, 20)
    assert result["wasserstein_to_historical"] >= 0.0


def test_stylized_facts_evaluation_keys():
    hist = _make_hist_returns()
    result = ddpm_synthetic_path_generator(hist, 20, 50)
    sf = result["stylized_facts_evaluation"]
    assert "fat_tails" in sf
    assert "vol_clustering" in sf
    assert "negative_skew" in sf
    assert isinstance(sf["fat_tails"], bool)
    assert isinstance(sf["vol_clustering"], bool)
    assert isinstance(sf["negative_skew"], bool)


def test_pandas_series_input():
    import pandas as pd

    hist = pd.Series(_make_hist_returns())
    result = ddpm_synthetic_path_generator(hist, 5, 10)
    assert result["synthetic_paths"].shape == (5, 10)


def test_invalid_inputs_raise():
    hist = _make_hist_returns()
    with pytest.raises(ValueError):
        ddpm_synthetic_path_generator(hist, n_synthetic_paths=0, path_length=10)
    with pytest.raises(ValueError):
        ddpm_synthetic_path_generator(hist, n_synthetic_paths=5, path_length=0)
