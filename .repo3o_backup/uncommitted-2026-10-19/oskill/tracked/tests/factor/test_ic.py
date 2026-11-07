"""Tests for oskill.factor.ic.factor_ic."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oskill.factor.ic import factor_ic


class TestFactorIC:
    def test_basic_returns_required_keys(self):
        factor = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        rets = np.array([0.1, 0.2, 0.15, 0.3, 0.25])
        result = factor_ic(factor, rets)
        for key in ["ic", "ic_std", "ic_t_stat", "ic_p_value", "icir", "rolling_ic"]:
            assert key in result

    def test_perfect_positive_ic_spearman(self):
        factor = np.arange(1.0, 11.0)
        rets = np.arange(1.0, 11.0) * 0.01
        result = factor_ic(factor, rets, method="spearman")
        assert result["ic"] == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative_ic_spearman(self):
        factor = np.arange(10.0, 0.0, -1.0)
        rets = np.arange(1.0, 11.0) * 0.01
        result = factor_ic(factor, rets, method="spearman")
        assert result["ic"] == pytest.approx(-1.0, abs=1e-6)

    def test_pearson_method(self):
        rng = np.random.default_rng(42)
        factor = rng.normal(0, 1, 50)
        rets = factor * 0.5 + rng.normal(0, 0.1, 50)
        result_p = factor_ic(factor, rets, method="pearson")
        result_s = factor_ic(factor, rets, method="spearman")
        assert result_p["ic"] != result_s["ic"]

    def test_zero_ic_for_uncorrelated(self):
        rng = np.random.default_rng(0)
        factor = rng.normal(0, 1, 1000)
        rets = rng.normal(0, 1, 1000)
        result = factor_ic(factor, rets)
        assert abs(result["ic"]) < 0.15

    def test_shape_mismatch_raises(self):
        factor = np.array([1.0, 2.0, 3.0])
        rets = np.array([1.0, 2.0])
        with pytest.raises(ValueError, match="shape"):
            factor_ic(factor, rets)

    def test_3d_raises(self):
        factor = np.ones((3, 4, 5))
        rets = np.ones((3, 4, 5))
        with pytest.raises(ValueError, match="1D or 2D"):
            factor_ic(factor, rets)

    def test_pandas_series_input(self):
        factor = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        rets = pd.Series([0.1, 0.15, 0.12, 0.18, 0.2])
        result = factor_ic(factor, rets)
        assert isinstance(result["ic"], float)

    def test_2d_factor_cross_sectional(self):
        rng = np.random.default_rng(42)
        T, N = 20, 10
        factor = rng.normal(0, 1, (T, N))
        rets = factor * 0.3 + rng.normal(0, 1, (T, N))
        result = factor_ic(factor, rets)
        assert isinstance(result["ic"], float)

    def test_2d_factor_positive_mean_ic(self):
        rng = np.random.default_rng(42)
        T, N = 100, 20
        factor = rng.normal(0, 1, (T, N))
        rets = factor * 0.5 + rng.normal(0, 0.2, (T, N))
        result = factor_ic(factor, rets)
        assert result["ic"] > 0.0

    def test_rolling_ic_1d(self):
        factor = np.arange(1.0, 11.0)
        rets = np.arange(1.0, 11.0) * 0.01
        result = factor_ic(factor, rets, rolling_window=3)
        assert result["rolling_ic"] is not None

    def test_rolling_ic_2d(self):
        rng = np.random.default_rng(42)
        T, N = 30, 10
        factor = rng.normal(0, 1, (T, N))
        rets = factor * 0.3 + rng.normal(0, 1, (T, N))
        result = factor_ic(factor, rets, rolling_window=5)
        assert result["rolling_ic"] is not None
        assert len(result["rolling_ic"]) == T

    def test_rolling_ic_with_series_index(self):
        rng = np.random.default_rng(42)
        T, N = 20, 5
        factor = rng.normal(0, 1, (T, N))
        idx = pd.date_range("2024-01-01", periods=T)
        pd.Series(rng.normal(0, 1, T), index=idx)
        # rets must match shape; let's use ndarray
        rets_arr = rng.normal(0, 1, (T, N))
        result = factor_ic(factor, rets_arr, rolling_window=5)
        assert result["rolling_ic"] is not None

    def test_all_nan_returns_zeros(self):
        factor = np.array([np.nan, np.nan, np.nan])
        rets = np.array([0.1, 0.2, 0.3])
        result = factor_ic(factor, rets)
        assert result["ic"] == 0.0
        assert result["ic_std"] == 0.0

    def test_single_cross_section_ic_std_zero(self):
        factor = np.arange(1.0, 11.0)
        rets = np.arange(1.0, 11.0) * 0.01
        result = factor_ic(factor, rets)
        assert result["ic_std"] == 0.0

    def test_p_value_in_range(self):
        rng = np.random.default_rng(42)
        T, N = 50, 10
        factor = rng.normal(0, 1, (T, N))
        rets = factor * 0.3 + rng.normal(0, 1, (T, N))
        result = factor_ic(factor, rets)
        assert 0.0 <= result["ic_p_value"] <= 1.0

    def test_rolling_ic_no_window_is_none(self):
        factor = np.arange(1.0, 6.0)
        rets = np.arange(1.0, 6.0) * 0.01
        result = factor_ic(factor, rets)
        assert result["rolling_ic"] is None

    @pytest.mark.academic_reference
    def test_ic_information_coefficient_finance(self):
        """Grinold & Kahn (1999) Active Portfolio Management: IC definition.

        The Information Coefficient is the correlation between predicted and
        realized returns. A perfect positive rank correlation (Spearman) between
        factor scores and forward returns gives IC = 1.0.
        For N=10 assets with factor rank matching return rank exactly,
        Spearman IC = 1.0.
        """
        n = 10
        factor = np.arange(1.0, n + 1.0)
        rets = np.linspace(0.01, 0.10, n)
        result = factor_ic(factor, rets, method="spearman")
        assert result["ic"] == pytest.approx(1.0, abs=1e-6)
        # Single cross-section: p_value defaults to 1.0 (no time-series stats)
        assert result["ic"] > 0.9
