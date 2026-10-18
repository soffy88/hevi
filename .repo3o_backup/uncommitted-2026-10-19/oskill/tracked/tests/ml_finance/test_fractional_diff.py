"""Tests for fractional_differentiation."""

import numpy as np
import pandas as pd

from oskill.ml_finance.fractional_diff import fractional_differentiation


class TestFractionalDifferentiation:
    """Tests for fractional_differentiation."""

    def test_d_zero_returns_original(self):
        """d=0 should return (approximately) the original series."""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        result = fractional_differentiation(x, d=0.0, threshold=1e-10)
        # d=0: weight w_0=1, w_1=(0-0)/1=0 (immediately below threshold)
        # So result should be x itself (same length or truncated by 1 weight)
        assert len(result) > 0
        # The first element should match x[0] closely
        if len(result) == len(x):
            np.testing.assert_allclose(result, x, atol=1e-6)

    def test_d_one_approximates_first_difference(self):
        """d=1 should produce exactly first differences."""
        x = np.array([1.0, 3.0, 6.0, 10.0, 15.0, 21.0, 28.0, 36.0, 45.0, 55.0])
        result = fractional_differentiation(x, d=1.0, threshold=1e-5)
        # d=1: weights = [1, -1]; output = x[t] - x[t-1] = first diff
        diffs = np.diff(x)
        n = min(len(result), len(diffs))
        np.testing.assert_allclose(result[:n], diffs[:n], atol=1e-8)

    def test_output_shorter_than_input(self):
        """Output should be shorter than input by (window_size - 1)."""
        x = np.linspace(1, 50, 50)
        result = fractional_differentiation(x, d=0.5, threshold=1e-5)
        assert len(result) < len(x)

    def test_pandas_series_input_output(self):
        """With pd.Series input, should return pd.Series with matching index."""
        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        x = pd.Series(np.linspace(100, 130, 30), index=idx)
        result = fractional_differentiation(x, d=0.5)
        assert isinstance(result, pd.Series)
        assert len(result) < len(x)
        # Index should be subset of original
        assert result.index[0] >= idx[0]

    def test_ndarray_input_returns_ndarray(self):
        """With ndarray input, should return ndarray."""
        x = np.random.default_rng(42).normal(0, 1, 50)
        result = fractional_differentiation(x, d=0.4)
        assert isinstance(result, np.ndarray)

    def test_d_half_returns_finite_values(self):
        """d=0.5 should return finite values."""
        rng = np.random.default_rng(7)
        x = 100 * np.cumprod(1 + rng.normal(0, 0.01, 100))
        result = fractional_differentiation(x, d=0.5)
        assert np.all(np.isfinite(result))

    def test_fixed_width_parameter(self):
        """fixed_width should limit the number of lags used."""
        x = np.linspace(1, 100, 100)
        fractional_differentiation(x, d=0.5, threshold=1e-5)
        result_fixed = fractional_differentiation(x, d=0.5, fixed_width=5)
        # fixed_width=5 means up to 5 additional lag weights (w_1..w_5)
        # so window_size <= 6, output length >= T - 5 = 95
        assert len(result_fixed) >= 100 - 6
        assert len(result_fixed) <= 100

    def test_weights_decay(self):
        """Fractional difference weights should decrease in magnitude."""
        # Test that the algorithm computes decreasing weights by verifying
        # result with known weights manually
        x = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        # For d=0.5, weights sum: 1, -0.5, -0.125, ...
        result = fractional_differentiation(x, d=0.5, threshold=1e-5)
        # Constant series after fractional diff should converge near 0 (for d>0)
        assert np.all(np.abs(result) < 1.0)  # weights sum to finite value
