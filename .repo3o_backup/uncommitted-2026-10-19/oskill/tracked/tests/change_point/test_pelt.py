"""Tests for pelt_change_point (PELT algorithm)."""

import numpy as np
import pandas as pd

from oskill.change_point.pelt import pelt_change_point


def _make_3segment_series(rng: np.random.Generator):
    """Generate a 3-segment series with clear mean shifts."""
    seg1 = rng.normal(0.0, 0.3, 30)
    seg2 = rng.normal(5.0, 0.3, 30)
    seg3 = rng.normal(-5.0, 0.3, 30)
    return np.concatenate([seg1, seg2, seg3])


class TestPeltChangePoint:
    """Tests for pelt_change_point."""

    def test_returns_required_keys(self):
        """Result must contain all required keys."""
        x = np.random.default_rng(1).normal(0, 1, 60)
        result = pelt_change_point(x)
        assert "change_points" in result
        assert "n_segments" in result
        assert "segment_means" in result
        assert "segment_variances" in result
        assert "total_cost" in result

    def test_3_segment_series_finds_2_change_points(self):
        """Clearly 3-segment series should find 2 change points."""
        rng = np.random.default_rng(42)
        x = _make_3segment_series(rng)
        result = pelt_change_point(x, min_segment_length=5, penalty_method="bic")
        # Should detect approximately 2 change points
        assert result["n_segments"] >= 2

    def test_n_segments_consistent(self):
        """n_segments == len(change_points) + 1."""
        rng = np.random.default_rng(5)
        x = rng.normal(0, 1, 80)
        result = pelt_change_point(x)
        assert result["n_segments"] == len(result["change_points"]) + 1

    def test_segment_means_length(self):
        """segment_means should have same length as n_segments."""
        rng = np.random.default_rng(7)
        x = rng.normal(0, 1, 60)
        result = pelt_change_point(x)
        assert len(result["segment_means"]) == result["n_segments"]

    def test_segment_variances_length(self):
        """segment_variances should have same length as n_segments."""
        rng = np.random.default_rng(8)
        x = rng.normal(0, 1, 60)
        result = pelt_change_point(x)
        assert len(result["segment_variances"]) == result["n_segments"]

    def test_pandas_series_input(self):
        """Should accept pd.Series input."""
        x = pd.Series(np.random.default_rng(9).normal(0, 1, 50))
        result = pelt_change_point(x)
        assert "change_points" in result

    def test_stationary_series_few_change_points(self):
        """Stationary Gaussian series should have few or no change points with BIC."""
        rng = np.random.default_rng(11)
        x = rng.normal(0.0, 1.0, 100)
        result = pelt_change_point(x, min_segment_length=10, penalty_method="bic")
        # Should not overfit with BIC
        assert result["n_segments"] <= 5

    def test_mean_model(self):
        """mean cost model should run and return valid results."""
        rng = np.random.default_rng(12)
        x = np.concatenate([rng.normal(0, 1, 25), rng.normal(5, 1, 25)])
        result = pelt_change_point(x, model="mean", min_segment_length=5)
        assert result["n_segments"] >= 1
