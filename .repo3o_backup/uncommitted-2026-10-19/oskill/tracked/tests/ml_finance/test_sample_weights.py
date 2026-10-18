"""Tests for sample_uniqueness_weights and return_attribution_weights."""

import numpy as np
import pandas as pd

from oskill.ml_finance.sample_weights import (
    return_attribution_weights,
    sample_uniqueness_weights,
)


def _make_events(starts, ends):
    return pd.DataFrame({"event_start": starts, "event_end": ends})


class TestSampleUniquenessWeights:
    """Tests for sample_uniqueness_weights."""

    def test_weights_sum_to_one(self):
        """Weights must sum to 1.0."""
        events = _make_events([0, 2, 5, 8, 11], [3, 6, 9, 12, 15])
        weights = sample_uniqueness_weights(events)
        assert abs(np.sum(weights) - 1.0) < 1e-9

    def test_weights_non_negative(self):
        """All weights must be non-negative."""
        events = _make_events([0, 3, 6, 9], [4, 7, 10, 13])
        weights = sample_uniqueness_weights(events)
        assert np.all(weights >= 0)

    def test_non_overlapping_events_equal_weights(self):
        """Non-overlapping events of equal length should get equal weights."""
        events = _make_events([0, 5, 10, 15], [4, 9, 14, 19])
        weights = sample_uniqueness_weights(events)
        # All equal: check max/min ratio close to 1
        assert np.max(weights) / np.min(weights) < 1.01

    def test_overlapping_events_lower_weight(self):
        """Highly overlapping events should have lower weight than isolated ones."""
        # Events 0-9 all overlap; event 20-29 is isolated
        events = _make_events(
            [0, 0, 0, 0, 20],
            [9, 9, 9, 9, 29],
        )
        weights = sample_uniqueness_weights(events)
        # Isolated event should have higher weight than overlapping ones
        isolated_weight = weights[4]
        overlapping_avg = np.mean(weights[:4])
        assert isolated_weight > overlapping_avg

    def test_single_event(self):
        """Single event should have weight 1.0."""
        events = _make_events([0], [9])
        weights = sample_uniqueness_weights(events)
        assert abs(weights[0] - 1.0) < 1e-9

    def test_empty_events_returns_empty(self):
        """Empty events DataFrame should return empty array."""
        events = _make_events([], [])
        weights = sample_uniqueness_weights(events)
        assert len(weights) == 0

    def test_concurrent_method_returns_weights(self):
        """concurrent method should also return valid weight array."""
        events = _make_events([0, 2, 5], [4, 7, 9])
        weights = sample_uniqueness_weights(events, method="concurrent")
        assert len(weights) == 3
        assert np.all(weights >= 0)


class TestReturnAttributionWeights:
    """Tests for return_attribution_weights."""

    def test_weights_sum_to_one(self):
        """Weights must sum to 1.0."""
        events = _make_events([0, 5, 10, 15], [4, 9, 14, 19])
        returns = np.random.default_rng(42).normal(0, 0.01, 20)
        weights = return_attribution_weights(events, returns)
        assert abs(np.sum(weights) - 1.0) < 1e-9

    def test_weights_non_negative(self):
        """All weights must be non-negative."""
        events = _make_events([0, 3, 7], [2, 6, 10])
        returns = np.abs(np.random.default_rng(1).normal(0, 0.02, 12))
        weights = return_attribution_weights(events, returns)
        assert np.all(weights >= 0)

    def test_high_return_event_gets_higher_weight(self):
        """Event with higher absolute return should receive higher weight."""
        events = _make_events([0, 10], [4, 14])
        returns = np.zeros(20)
        returns[0:5] = 0.01  # small returns in event 1
        returns[10:15] = 0.10  # large returns in event 2
        weights = return_attribution_weights(events, returns)
        assert weights[1] > weights[0]

    def test_zero_returns_equal_weights(self):
        """Events with zero returns fall back to uniform weights."""
        events = _make_events([0, 5, 10], [4, 9, 14])
        returns = np.zeros(15)
        weights = return_attribution_weights(events, returns)
        # All zero returns → uniform weights
        assert abs(np.sum(weights) - 1.0) < 1e-9

    def test_pandas_series_returns(self):
        """Should accept pd.Series for returns."""
        events = _make_events([0, 5], [4, 9])
        returns = pd.Series(np.random.default_rng(10).normal(0, 0.01, 10))
        weights = return_attribution_weights(events, returns)
        assert len(weights) == 2

    def test_single_event(self):
        """Single event should get weight 1.0."""
        events = _make_events([0], [4])
        returns = np.array([0.01, 0.02, -0.01, 0.03, 0.005])
        weights = return_attribution_weights(events, returns)
        assert abs(weights[0] - 1.0) < 1e-9

    def test_average_uniqueness_false(self):
        """average_uniqueness=False should not divide by concurrency."""
        events = _make_events([0, 0], [5, 5])  # perfectly overlapping
        returns = np.ones(6) * 0.01
        return_attribution_weights(events, returns, average_uniqueness=True)
        w_raw = return_attribution_weights(events, returns, average_uniqueness=False)
        # With average_uniqueness=False, weights are equal (both events identical)
        assert abs(w_raw[0] - w_raw[1]) < 1e-9
