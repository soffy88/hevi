"""Tests for hawkes_branching_ratio."""

import numpy as np
import pytest

from oskill.microstructure.hawkes import hawkes_branching_ratio


def make_hawkes_times(n: int = 50, seed: int = 42) -> np.ndarray:
    """Generate synthetic event times (Poisson process approximation)."""
    rng = np.random.default_rng(seed)
    inter_arrivals = rng.exponential(0.5, n)
    times = np.cumsum(inter_arrivals)
    return times


class TestHawkesBranchingRatio:
    def test_returns_dict_keys(self):
        times = make_hawkes_times(30)
        result = hawkes_branching_ratio(times, hawkes_params={"mu": 0.5, "alpha": 0.3, "beta": 1.0})
        assert "branching_ratio" in result
        assert "stability_status" in result
        assert "hawkes_params" in result
        assert "half_life" in result

    def test_stable_status(self):
        """n < 0.8 should be stable."""
        result = hawkes_branching_ratio(
            make_hawkes_times(20), hawkes_params={"mu": 0.5, "alpha": 0.3, "beta": 1.0}
        )
        assert result["branching_ratio"] == pytest.approx(0.3)
        assert result["stability_status"] == "stable"

    def test_near_critical_status(self):
        """0.8 <= n < 1.0 → near_critical."""
        result = hawkes_branching_ratio(
            make_hawkes_times(20), hawkes_params={"mu": 0.5, "alpha": 0.85, "beta": 1.0}
        )
        assert result["stability_status"] == "near_critical"

    def test_unstable_status(self):
        """n >= 1.0 → unstable."""
        result = hawkes_branching_ratio(
            make_hawkes_times(20), hawkes_params={"mu": 0.5, "alpha": 1.5, "beta": 1.0}
        )
        assert result["stability_status"] == "unstable"

    def test_branching_ratio_formula(self):
        """n = alpha / beta."""
        alpha, beta = 0.6, 2.0
        result = hawkes_branching_ratio(
            make_hawkes_times(20), hawkes_params={"mu": 0.3, "alpha": alpha, "beta": beta}
        )
        assert result["branching_ratio"] == pytest.approx(alpha / beta)

    def test_half_life_formula(self):
        """half_life = ln(2) / beta."""
        import math

        beta = 2.5
        result = hawkes_branching_ratio(
            make_hawkes_times(20), hawkes_params={"mu": 0.3, "alpha": 0.5, "beta": beta}
        )
        assert result["half_life"] == pytest.approx(math.log(2) / beta)

    def test_fit_from_events(self):
        """Without hawkes_params, should fit and return valid result."""
        times = make_hawkes_times(60)
        result = hawkes_branching_ratio(times)
        assert "branching_ratio" in result
        assert result["branching_ratio"] >= 0
        assert result["stability_status"] in {"stable", "near_critical", "unstable"}

    def test_degenerate_single_event(self):
        """Single event should not crash."""
        times = np.array([1.0])
        result = hawkes_branching_ratio(times)
        assert "branching_ratio" in result
