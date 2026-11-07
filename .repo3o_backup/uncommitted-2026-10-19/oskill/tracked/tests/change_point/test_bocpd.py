"""Tests for bocpd_bayesian (Bayesian Online Change Point Detection)."""

import numpy as np
import pandas as pd

from oskill.change_point.bayesian_online import bocpd_bayesian


def _make_mean_shift_series(
    rng: np.random.Generator,
    n1: int = 50,
    n2: int = 50,
    mu1: float = 0.0,
    mu2: float = 5.0,
    sigma: float = 0.5,
):
    """Generate series with one mean shift."""
    seg1 = rng.normal(mu1, sigma, n1)
    seg2 = rng.normal(mu2, sigma, n2)
    return np.concatenate([seg1, seg2])


class TestBocpdBayesian:
    """Tests for bocpd_bayesian."""

    def test_returns_required_keys(self):
        """Result must contain all required keys."""
        x = np.arange(20, dtype=float)
        result = bocpd_bayesian(x)
        assert "change_points" in result
        assert "run_lengths" in result
        assert "map_run_length" in result
        assert "n_change_points" in result

    def test_detects_mean_shift(self):
        """Should detect change point in series with clear mean shift."""
        rng = np.random.default_rng(42)
        x = _make_mean_shift_series(rng, n1=40, n2=40, mu1=0.0, mu2=10.0, sigma=0.3)
        result = bocpd_bayesian(x, hazard_rate=0.01, min_segment_length=5)
        assert result["n_change_points"] >= 1
        # Change point should be near index 40
        cps = result["change_points"]
        nearest = min(cps, key=lambda c: abs(c - 40))
        assert abs(nearest - 40) <= 10

    def test_map_run_length_shape(self):
        """map_run_length should have same length as input."""
        x = np.random.default_rng(1).normal(0, 1, 60)
        result = bocpd_bayesian(x)
        assert len(result["map_run_length"]) == len(x)

    def test_run_lengths_shape(self):
        """run_lengths should be T x T array."""
        T = 30
        x = np.random.default_rng(2).normal(0, 1, T)
        result = bocpd_bayesian(x)
        rl = result["run_lengths"]
        assert rl.shape == (T, T)

    def test_no_change_point_stationary_series(self):
        """Stationary series should have few or no detected change points."""
        rng = np.random.default_rng(9)
        x = rng.normal(5.0, 0.5, 80)
        result = bocpd_bayesian(x, hazard_rate=0.01, min_segment_length=10)
        # Should not detect too many spurious change points
        assert result["n_change_points"] <= 5

    def test_pandas_input_accepted(self):
        """Should accept pd.Series input."""
        x = pd.Series(np.random.default_rng(3).normal(0, 1, 40))
        result = bocpd_bayesian(x)
        assert "change_points" in result

    def test_student_t_model_runs(self):
        """studentt model should run without errors."""
        x = np.random.default_rng(5).standard_t(df=3, size=40)
        result = bocpd_bayesian(x, model="studentt", hazard_rate=0.02)
        assert "change_points" in result

    def test_n_change_points_consistent(self):
        """n_change_points should equal len(change_points)."""
        x = np.random.default_rng(6).normal(0, 1, 50)
        result = bocpd_bayesian(x)
        assert result["n_change_points"] == len(result["change_points"])
