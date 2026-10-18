"""Tests for oskill.performance.subject_forward_winrate (S3)."""

import pytest

from oskill.performance import subject_forward_winrate


class TestSubjectForwardWinrate:
    def test_single_subject_win(self) -> None:
        events = [{"date": "2024-01-01", "symbol": "A"}]
        prices = {"A": [100, 105, 110, 108]}
        result = subject_forward_winrate(events=events, prices=prices, forward_window_days=3)
        assert result["winrate"] == 1.0
        assert result["wins"] == 1

    def test_price_insufficient_skip(self) -> None:
        events = [{"date": "2024-01-01", "symbol": "A"}]
        prices = {"A": [100]}  # Not enough for forward window
        result = subject_forward_winrate(events=events, prices=prices, forward_window_days=3)
        assert result["n_events_valid"] == 0

    def test_any_positive_vs_final_positive(self) -> None:
        events = [{"date": "2024-01-01", "symbol": "A"}]
        prices = {"A": [100, 105, 95, 90]}  # Day 1 positive, final negative
        r_any = subject_forward_winrate(
            events=events, prices=prices, forward_window_days=3, win_mode="any_positive"
        )
        r_final = subject_forward_winrate(
            events=events, prices=prices, forward_window_days=3, win_mode="final_positive"
        )
        assert r_any["winrate"] == 1.0  # Day 1 was positive
        assert r_final["winrate"] == 0.0  # Final day negative

    def test_empty_events(self) -> None:
        result = subject_forward_winrate(events=[], prices={}, forward_window_days=3)
        assert result["winrate"] is None
        assert result["n_events_total"] == 0

    def test_forward_zero_raises(self) -> None:
        with pytest.raises(ValueError):
            subject_forward_winrate(
                events=[{"symbol": "A"}], prices={"A": [100, 101]}, forward_window_days=0
            )

    def test_multiple_events(self) -> None:
        events = [
            {"date": "2024-01-01", "symbol": "A"},
            {"date": "2024-01-02", "symbol": "B"},
        ]
        prices = {"A": [100, 105, 110, 115], "B": [100, 95, 90, 85]}
        result = subject_forward_winrate(events=events, prices=prices, forward_window_days=3)
        assert result["winrate"] == 0.5
        assert result["wins"] == 1
        assert result["losses"] == 1
