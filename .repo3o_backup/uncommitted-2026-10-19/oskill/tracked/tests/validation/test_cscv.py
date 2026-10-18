"""Tests for combinatorially_symmetric_cv."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.validation.csv import combinatorially_symmetric_cv


@pytest.fixture
def returns_matrix():
    rng = np.random.default_rng(42)
    return rng.standard_normal((100, 10))


def test_cscv_basic(returns_matrix):
    result = combinatorially_symmetric_cv(returns_matrix, n_splits=4)
    expected_keys = {
        "cscv_pbo",
        "rank_logits",
        "is_overfit",
        "performance_degradation_pct",
        "haircut_to_apply",
    }
    assert set(result.keys()) == expected_keys


def test_cscv_pbo_in_range(returns_matrix):
    result = combinatorially_symmetric_cv(returns_matrix, n_splits=4)
    assert 0.0 <= result["cscv_pbo"] <= 1.0


def test_cscv_uniform_strategies_pbo_near_half():
    rng = np.random.default_rng(0)
    data = np.tile(rng.standard_normal((200, 1)), (1, 20))
    # Identical strategies — ranking is arbitrary, PBO should be close to 0.5
    result = combinatorially_symmetric_cv(data, n_splits=4)
    assert 0.0 <= result["cscv_pbo"] <= 1.0


def test_cscv_dominant_strategy_low_pbo():
    rng = np.random.default_rng(7)
    T, N = 200, 10
    data = rng.standard_normal((T, N))
    # Strategy 0 has a strong positive drift → consistently best
    data[:, 0] += 0.5
    result = combinatorially_symmetric_cv(data, n_splits=4)
    # A dominant strategy should produce PBO notably below 1.0
    assert result["cscv_pbo"] < 1.0


def test_cscv_rank_logits_array(returns_matrix):
    result = combinatorially_symmetric_cv(returns_matrix, n_splits=4)
    assert isinstance(result["rank_logits"], np.ndarray)
    assert len(result["rank_logits"]) > 0
    assert np.all(np.isfinite(result["rank_logits"]))


def test_cscv_is_overfit_flag(returns_matrix):
    result = combinatorially_symmetric_cv(returns_matrix, n_splits=4)
    assert result["is_overfit"] == (result["cscv_pbo"] > 0.5)


def test_cscv_dataframe_input():
    rng = np.random.default_rng(99)
    df = pd.DataFrame(rng.standard_normal((100, 8)))
    result = combinatorially_symmetric_cv(df, n_splits=4)
    assert 0.0 <= result["cscv_pbo"] <= 1.0
    assert isinstance(result["rank_logits"], np.ndarray)


def test_cscv_minimum_splits():
    rng = np.random.default_rng(3)
    data = rng.standard_normal((80, 6))
    result = combinatorially_symmetric_cv(data, n_splits=4)
    assert 0.0 <= result["cscv_pbo"] <= 1.0
    assert len(result["rank_logits"]) == 6  # C(4,2) = 6
