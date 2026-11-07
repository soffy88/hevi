"""Tests for full_combinatorial_purged_cv."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.validation.full_cpcv import full_combinatorial_purged_cv


class _SimpleRegressor:
    def fit(self, X, y):
        self._mean = np.mean(y)
        return self

    def predict(self, X):
        return np.full(len(X), self._mean)


class _SimpleClassifier:
    def fit(self, X, y):
        if hasattr(y, "mode"):
            self._cls = y.mode().iloc[0]
        else:
            self._cls = np.bincount(y.astype(int)).argmax()
        return self

    def predict(self, X):
        return np.full(len(X), self._cls)


@pytest.fixture
def reg_data():
    rng = np.random.default_rng(42)
    T = 300
    X = pd.DataFrame(rng.standard_normal((T, 3)))
    y = pd.Series(rng.standard_normal(T))
    return X, y


@pytest.fixture
def clf_data():
    rng = np.random.default_rng(42)
    T = 300
    X = pd.DataFrame(rng.standard_normal((T, 3)))
    y = pd.Series(rng.integers(0, 2, T))
    return X, y


def test_full_cpcv_basic(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=10, seed=0)
    expected_keys = {
        "mean_score",
        "score_distribution",
        "std_score",
        "p_values",
        "haircut_estimate",
        "n_paths_run",
        "embargo_periods",
    }
    assert set(result.keys()) == expected_keys


def test_full_cpcv_score_distribution_shape(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=20, seed=1)
    assert isinstance(result["score_distribution"], np.ndarray)
    assert len(result["score_distribution"]) > 0


def test_full_cpcv_n_paths_run_le_n_paths(reg_data):
    X, y = reg_data
    n_paths = 30
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=n_paths, seed=2)
    assert result["n_paths_run"] <= n_paths


def test_full_cpcv_embargo_periods_computed(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(
        X, y, _SimpleRegressor(), embargo_pct=0.05, n_paths=5, seed=3
    )
    assert result["embargo_periods"] >= 1


def test_full_cpcv_mean_score_is_float(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=10, seed=4)
    assert isinstance(result["mean_score"], float)
    assert np.isfinite(result["mean_score"])


def test_full_cpcv_classifier_estimator(clf_data):
    X, y = clf_data
    result = full_combinatorial_purged_cv(X, y, _SimpleClassifier(), n_paths=10, seed=5)
    assert 0.0 <= result["mean_score"] <= 1.0


def test_full_cpcv_regressor_estimator(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=10, seed=6)
    assert np.isfinite(result["mean_score"])


def test_full_cpcv_haircut_estimate_is_float(reg_data):
    X, y = reg_data
    result = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=15, seed=7)
    assert isinstance(result["haircut_estimate"], float)
    assert np.isfinite(result["haircut_estimate"])


def test_full_cpcv_seed_reproducible(reg_data):
    X, y = reg_data
    r1 = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=20, seed=99)
    r2 = full_combinatorial_purged_cv(X, y, _SimpleRegressor(), n_paths=20, seed=99)
    np.testing.assert_array_equal(r1["score_distribution"], r2["score_distribution"])
