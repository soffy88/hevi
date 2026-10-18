"""Tests for order_book_state_hawkes."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.microstructure.state_hawkes import order_book_state_hawkes


def make_events(
    n: int = 80, n_types: int = 2, seed: int = 42
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic event data."""
    rng = np.random.default_rng(seed)
    inter_arrivals = rng.exponential(0.5, n)
    times = np.cumsum(inter_arrivals)
    types = rng.integers(0, n_types, size=n)
    states = rng.uniform(0, 1, size=n)
    return times, types, states


class TestOrderBookStateHawkesBasic:
    def test_returns_dict_keys(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert "baseline" in result
        assert "excitation" in result
        assert "state_response" in result
        assert "log_likelihood" in result
        assert "branching_ratio" in result

    def test_baseline_shape(self):
        times, types, states = make_events(n_types=2)
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert result["baseline"].shape == (2,)

    def test_excitation_shape(self):
        times, types, states = make_events(n_types=3)
        result = order_book_state_hawkes(times, types, states, n_event_types=3)
        assert result["excitation"].shape == (3, 3)

    def test_state_response_shape(self):
        """state_response should have shape (n_bins, n_types)."""
        times, types, states = make_events(n_types=2)
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        # n_bins = 5, n_types = 2
        assert result["state_response"].shape == (5, 2)

    def test_baseline_positive(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert np.all(result["baseline"] > 0)

    def test_branching_ratio_positive(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert result["branching_ratio"] > 0

    def test_log_likelihood_finite(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert np.isfinite(result["log_likelihood"])

    def test_state_response_positive(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(times, types, states, n_event_types=2)
        assert np.all(result["state_response"] > 0)


class TestOrderBookStateHawkesVariants:
    def test_additive_state_function(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(
            times, types, states, n_event_types=2, state_function="additive"
        )
        assert result["baseline"].shape == (2,)
        assert result["branching_ratio"] > 0

    def test_spread_state_variable(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(
            times, types, states, n_event_types=2, state_variable="spread"
        )
        assert "baseline" in result

    def test_depth_state_variable(self):
        times, types, states = make_events()
        result = order_book_state_hawkes(
            times, types, states, n_event_types=2, state_variable="depth"
        )
        assert "state_response" in result

    def test_single_event_type(self):
        rng = np.random.default_rng(0)
        times = np.cumsum(rng.exponential(0.5, 50))
        types = np.zeros(50, dtype=int)
        states = rng.uniform(0, 1, 50)
        result = order_book_state_hawkes(times, types, states, n_event_types=1)
        assert result["baseline"].shape == (1,)
        assert result["excitation"].shape == (1, 1)


class TestOrderBookStateHawkesValidation:
    def test_non_increasing_times_raises(self):
        times = np.array([1.0, 0.5, 2.0])
        types = np.array([0, 0, 0])
        states = np.array([0.5, 0.5, 0.5])
        with pytest.raises(ValueError, match="strictly increasing"):
            order_book_state_hawkes(times, types, states, n_event_types=1)

    def test_invalid_event_types_raises(self):
        rng = np.random.default_rng(1)
        times = np.cumsum(rng.exponential(0.5, 20))
        types = np.full(20, 5, dtype=int)  # out of range for n_event_types=2
        states = rng.uniform(0, 1, 20)
        with pytest.raises(ValueError, match="event_types must be in"):
            order_book_state_hawkes(times, types, states, n_event_types=2)

    def test_mismatched_lengths_raises(self):
        times = np.cumsum(np.ones(10))
        types = np.zeros(8, dtype=int)
        states = np.zeros(10)
        with pytest.raises(ValueError, match="same length"):
            order_book_state_hawkes(times, types, states, n_event_types=1)
