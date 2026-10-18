"""Tests for random_subsampling_validation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.backtest.random_subsampling import random_subsampling_validation


class _SimpleRegressor:
    def fit(self, X, y):
        self._mean = np.mean(y)
        return self

    def predict(self, X):
        return np.full(len(X), self._mean)


@pytest.fixture
def reg_data():
    rng = np.random.default_rng(42)
    T = 300
    X = pd.DataFrame(rng.standard_normal((T, 3)))
    y = pd.Series(rng.standard_normal(T))
    return X, y


def test_rss_basic(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=20, seed=0)
    expected_keys = {
        "mean_score",
        "std_score",
        "score_distribution",
        "score_5th_pct",
        "score_95th_pct",
        "n_iterations_completed",
    }
    assert set(result.keys()) == expected_keys


def test_rss_n_iterations_completed(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=50, seed=1)
    assert result["n_iterations_completed"] <= 50
    assert result["n_iterations_completed"] > 0


def test_rss_mean_score_is_float(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=20, seed=2)
    assert isinstance(result["mean_score"], float)
    assert np.isfinite(result["mean_score"])


def test_rss_score_distribution_shape(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=30, seed=3)
    assert isinstance(result["score_distribution"], np.ndarray)
    assert len(result["score_distribution"]) == result["n_iterations_completed"]


def test_rss_percentiles_ordered(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=50, seed=4)
    assert result["score_5th_pct"] <= result["score_95th_pct"]


def test_rss_seed_reproducible(reg_data):
    X, y = reg_data
    r1 = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=30, seed=77)
    r2 = random_subsampling_validation(X, y, _SimpleRegressor(), n_iterations=30, seed=77)
    np.testing.assert_array_equal(r1["score_distribution"], r2["score_distribution"])


def test_rss_with_embargo(reg_data):
    X, y = reg_data
    result = random_subsampling_validation(
        X, y, _SimpleRegressor(), n_iterations=20, embargo_pct=0.05, seed=5
    )
    assert result["n_iterations_completed"] > 0
    assert np.isfinite(result["mean_score"])
