"""Tests for triple_barrier_label."""

import numpy as np
import pandas as pd

from oskill.ml_finance.triple_barrier import triple_barrier_label


class TestTripleBarrierLabel:
    """Tests for triple_barrier_label function."""

    def test_returns_required_keys(self):
        """Result dict must contain all required keys."""
        prices = np.array([100.0, 102.0, 103.0, 99.0, 104.0, 98.0])
        result = triple_barrier_label(prices)
        assert "labels" in result
        assert "label_dates" in result
        assert "meta_labels" in result
        assert "n_positive" in result
        assert "n_negative" in result
        assert "n_neutral" in result

    def test_labels_sum_to_n_obs(self):
        """n_positive + n_negative + n_neutral should equal number of observations."""
        rng = np.random.default_rng(42)
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, 50))
        result = triple_barrier_label(
            prices, upper_barrier=0.02, lower_barrier=-0.02, time_barrier=5
        )
        n = len(prices)
        total = result["n_positive"] + result["n_negative"] + result["n_neutral"]
        assert total == n

    def test_labels_only_valid_values(self):
        """Labels must be in {-1, 0, 1}."""
        rng = np.random.default_rng(99)
        prices = 100 * np.cumprod(1 + rng.normal(0, 0.02, 100))
        result = triple_barrier_label(prices)
        unique_labels = set(result["labels"].tolist())
        assert unique_labels.issubset({-1, 0, 1})

    def test_upper_barrier_hit(self):
        """Steadily rising prices should produce positive labels."""
        # Prices that always hit upper barrier
        prices = np.array([100.0, 103.0, 106.0, 109.0, 112.0, 115.0, 118.0, 121.0])
        result = triple_barrier_label(
            prices, upper_barrier=0.02, lower_barrier=-0.05, time_barrier=3
        )
        # Most should be +1
        assert result["n_positive"] > 0

    def test_lower_barrier_hit(self):
        """Steadily falling prices should produce negative labels."""
        prices = np.array([100.0, 97.0, 94.0, 91.0, 88.0, 85.0, 82.0, 79.0])
        result = triple_barrier_label(
            prices, upper_barrier=0.05, lower_barrier=-0.02, time_barrier=3
        )
        assert result["n_negative"] > 0

    def test_time_barrier_produces_neutral(self):
        """Flat prices (no barrier hit) should produce neutral labels."""
        # Exactly flat: no barrier hit within time window
        prices = np.ones(20) * 100.0
        result = triple_barrier_label(
            prices, upper_barrier=0.10, lower_barrier=-0.10, time_barrier=3
        )
        # All should be neutral
        assert result["n_neutral"] == 20

    def test_meta_labels_without_side(self):
        """Without side, meta_labels should be all zeros."""
        prices = np.array([100.0, 102.0, 98.0, 101.0, 97.0])
        result = triple_barrier_label(prices)
        assert np.all(result["meta_labels"] == 0)

    def test_meta_labels_with_side(self):
        """With side that matches label, meta_label = 1."""
        prices = np.array([100.0, 103.0, 106.0, 109.0, 112.0, 115.0])
        side = np.array([1, 1, 1, 1, 1, 1])
        result = triple_barrier_label(
            prices, upper_barrier=0.02, lower_barrier=-0.05, time_barrier=2, side=side
        )
        # Where label==1 and side==1, meta_label should be 1
        labels = result["labels"]
        meta = result["meta_labels"]
        for i in range(len(labels)):
            if labels[i] == 1 and side[i] == 1:
                assert meta[i] == 1

    def test_pandas_series_input(self):
        """Should accept pd.Series input and return numpy arrays."""
        prices = pd.Series([100.0, 102.0, 99.0, 103.0, 101.0, 98.0])
        result = triple_barrier_label(prices, time_barrier=2)
        assert isinstance(result["labels"], np.ndarray)
        assert len(result["labels"]) == len(prices)

    def test_label_dates_length(self):
        """label_dates should have same length as prices."""
        prices = np.linspace(100, 110, 15)
        result = triple_barrier_label(prices, time_barrier=3)
        assert len(result["label_dates"]) == len(prices)
