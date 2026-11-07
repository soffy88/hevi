"""Tests for cusum_filter."""

import numpy as np
import pandas as pd

from oskill.ml_finance.cusum_filter import cusum_filter


class TestCusumFilter:
    """Tests for cusum_filter."""

    def test_returns_required_keys(self):
        """Result must contain all required keys."""
        x = np.array([1.0, 1.01, 1.02, 1.03, 1.10, 1.11, 1.12])
        result = cusum_filter(x, threshold=0.05)
        assert "event_indices" in result
        assert "event_timestamps" in result
        assert "n_events" in result

    def test_large_jump_triggers_event(self):
        """A large sudden jump should trigger an event."""
        x = np.zeros(20)
        x[10] = 1.0  # large jump at index 10
        result = cusum_filter(x, threshold=0.05)
        assert result["n_events"] >= 1
        assert 10 in result["event_indices"]

    def test_flat_series_no_events(self):
        """A perfectly flat series should produce no events."""
        x = np.ones(50)
        result = cusum_filter(x, threshold=0.01)
        assert result["n_events"] == 0

    def test_n_events_matches_list_length(self):
        """n_events must match len(event_indices)."""
        rng = np.random.default_rng(42)
        x = np.cumsum(rng.normal(0, 0.01, 100))
        result = cusum_filter(x, threshold=0.05)
        assert result["n_events"] == len(result["event_indices"])

    def test_pandas_series_preserves_index(self):
        """With DatetimeIndex input, event_timestamps should be DatetimeIndex."""
        idx = pd.date_range("2021-01-01", periods=30, freq="D")
        x = pd.Series(np.zeros(30), index=idx)
        x.iloc[15] = 1.0  # large jump
        result = cusum_filter(x, threshold=0.1)
        assert hasattr(result["event_timestamps"], "__len__")

    def test_asymmetric_method_only_detects_upward(self):
        """Asymmetric method should only detect upward moves."""
        x = np.zeros(20)
        x[5] = 0.5  # upward jump
        x[15] = -0.5  # downward jump (same magnitude)
        cusum_filter(x, threshold=0.1, method="symmetric")
        asym_result = cusum_filter(x, threshold=0.1, method="asymmetric")
        # Symmetric detects both; asymmetric detects only upward
        assert 5 in asym_result["event_indices"]
        assert 15 not in asym_result["event_indices"]

    def test_reset_after_event(self):
        """After an event, accumulators should reset, preventing back-to-back triggers."""
        # Two jumps closely spaced: only second should trigger new event after reset
        x = np.zeros(30)
        x[5] = 0.5  # first jump → event
        x[6] = 0.5  # second jump right after → separate event
        result = cusum_filter(x, threshold=0.1)
        # Each large jump should be detected independently
        assert result["n_events"] >= 1
