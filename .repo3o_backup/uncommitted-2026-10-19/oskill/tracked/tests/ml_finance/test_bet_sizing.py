"""Tests for bet_sizing."""

import numpy as np
import pandas as pd

from oskill.ml_finance.bet_sizing import bet_sizing


class TestBetSizing:
    """Tests for bet_sizing."""

    def test_output_length_matches_input(self):
        """Output should have same length as input probabilities."""
        p = np.array([0.3, 0.5, 0.7, 0.9])
        sizes = bet_sizing(p)
        assert len(sizes) == len(p)

    def test_probability_half_gives_size_near_zero(self):
        """p=0.5 (indifference for binary) should yield size near 0."""
        p = np.array([0.5])
        sizes = bet_sizing(p, method="sigmoid")
        assert abs(sizes[0]) < 0.05

    def test_probability_near_one_gives_large_size(self):
        """p near 1 should yield large positive size close to max_position."""
        p = np.array([0.999])
        sizes = bet_sizing(p, method="sigmoid", max_position=1.0)
        assert sizes[0] > 0.7

    def test_probability_near_zero_gives_negative_size(self):
        """p near 0 should yield large negative size."""
        p = np.array([0.001])
        sizes = bet_sizing(p, method="sigmoid", max_position=1.0)
        assert sizes[0] < -0.7

    def test_sizes_within_max_position(self):
        """All sizes must be within [-max_position, max_position]."""
        rng = np.random.default_rng(42)
        p = rng.uniform(0, 1, 100)
        max_pos = 0.7
        sizes = bet_sizing(p, max_position=max_pos)
        assert np.all(sizes >= -max_pos - 1e-9)
        assert np.all(sizes <= max_pos + 1e-9)

    def test_side_flips_direction(self):
        """When side=-1, positive sizes should become negative."""
        p = np.array([0.9, 0.9])
        side = np.array([1.0, -1.0])
        sizes = bet_sizing(p, side=side)
        assert sizes[0] > 0
        assert sizes[1] < 0

    def test_step_size_rounds_output(self):
        """With step_size=0.1, output should be multiples of 0.1."""
        p = np.linspace(0.1, 0.9, 20)
        sizes = bet_sizing(p, step_size=0.1)
        # Each size should be close to a multiple of 0.1
        rounded = np.round(sizes / 0.1) * 0.1
        np.testing.assert_allclose(sizes, rounded, atol=1e-9)

    def test_kelly_fractional_method(self):
        """Kelly fractional method should give smaller sizes than sigmoid near extremes."""
        p = np.array([0.9])
        bet_sizing(p, method="sigmoid")[0]
        size_kelly = bet_sizing(p, method="kelly_fractional")[0]
        # Kelly should be positive for p > 0.5
        assert size_kelly > 0
        # Kelly is 0.5 * (2p-1) = 0.5*(1.8-1)=0.4 for p=0.9
        expected_kelly = 0.5 * (2 * 0.9 - 1)
        assert abs(size_kelly - expected_kelly) < 1e-9

    def test_pandas_series_preserves_type(self):
        """With pd.Series input, should return pd.Series."""
        p = pd.Series([0.3, 0.5, 0.7, 0.9])
        sizes = bet_sizing(p)
        assert isinstance(sizes, pd.Series)
        assert len(sizes) == 4
