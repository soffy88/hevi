"""Tests for oskill.factor.disclosure_scoring."""

from __future__ import annotations

from datetime import date

import pytest

from oskill.factor.disclosure_scoring import disclosure_event_scoring


def _make_dims():
    return [
        {
            "name": "market_recognition",
            "max_score": 50,
            "method": "direct",
            "params": {"field": "buy_amount", "max": 1e8},
        }
    ]


class TestDisclosureEventScoring:
    def test_empty_events_returns_empty(self):
        result = disclosure_event_scoring([], _make_dims(), {"market_recognition": 1.0})
        assert result == []

    def test_single_event_has_required_keys(self):
        events = [{"symbol": "600519", "date": date(2024, 1, 1), "buy_amount": 5e7}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert len(result) == 1
        r = result[0]
        assert "symbol" in r
        assert "total_score" in r
        assert "scores_by_dimension" in r

    def test_total_score_range(self):
        events = [{"symbol": "X", "date": date(2024, 1, 1), "buy_amount": 5e7}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert 0.0 <= result[0]["total_score"] <= 50.0

    def test_zero_amount_gives_zero_score(self):
        events = [{"symbol": "X", "date": date(2024, 1, 1), "buy_amount": 0}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert result[0]["total_score"] == pytest.approx(0.0)

    def test_max_amount_gives_max_score(self):
        events = [{"symbol": "X", "date": date(2024, 1, 1), "buy_amount": 1e8}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert result[0]["total_score"] == pytest.approx(50.0)

    def test_over_max_amount_capped(self):
        events = [{"symbol": "X", "date": date(2024, 1, 1), "buy_amount": 2e8}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert result[0]["total_score"] == pytest.approx(50.0)

    def test_percentile_method(self):
        dims = [
            {
                "name": "rank",
                "max_score": 100,
                "method": "percentile",
                "params": {"field": "volume", "reference": [100, 200, 300, 400, 500]},
            }
        ]
        events = [{"symbol": "X", "date": date(2024, 1, 1), "volume": 300}]
        result = disclosure_event_scoring(events, dims, {"rank": 1.0})
        # 3 of 5 values <= 300, percentile rank = 3/5 = 0.6, score = 60
        assert result[0]["total_score"] == pytest.approx(60.0)

    def test_percentile_method_empty_reference_gives_zero(self):
        dims = [
            {
                "name": "rank",
                "max_score": 100,
                "method": "percentile",
                "params": {"field": "volume", "reference": []},
            }
        ]
        events = [{"symbol": "X", "date": date(2024, 1, 1), "volume": 300}]
        result = disclosure_event_scoring(events, dims, {"rank": 1.0})
        assert result[0]["total_score"] == pytest.approx(0.0)

    def test_context_method_uses_history_lookup(self):
        dims = [
            {
                "name": "hist_score",
                "max_score": 100,
                "method": "context",
                "params": {"field": "base_rate"},
            }
        ]

        def lookup(symbol, date):
            return {"base_rate": 75.0}

        events = [{"symbol": "X", "date": date(2024, 1, 1)}]
        result = disclosure_event_scoring(events, dims, {"hist_score": 1.0}, history_lookup=lookup)
        assert result[0]["total_score"] == pytest.approx(75.0)

    def test_context_method_no_lookup_gives_zero(self):
        dims = [
            {
                "name": "hist_score",
                "max_score": 100,
                "method": "context",
                "params": {"field": "base_rate"},
            }
        ]
        events = [{"symbol": "X", "date": date(2024, 1, 1)}]
        result = disclosure_event_scoring(events, dims, {"hist_score": 1.0})
        assert result[0]["total_score"] == pytest.approx(0.0)

    def test_weights_normalized_when_not_summing_to_one(self):
        dims = [
            {
                "name": "A",
                "max_score": 100,
                "method": "direct",
                "params": {"field": "a", "max": 100},
            },
            {
                "name": "B",
                "max_score": 100,
                "method": "direct",
                "params": {"field": "b", "max": 100},
            },
        ]
        events = [{"symbol": "X", "date": date(2024, 1, 1), "a": 100, "b": 100}]
        result = disclosure_event_scoring(events, dims, {"A": 1.0, "B": 1.0})
        # equal weights after normalization -> avg of 100+100=100
        assert result[0]["total_score"] == pytest.approx(100.0)

    def test_multiple_events_processed(self):
        events = [
            {"symbol": "A", "date": date(2024, 1, 1), "buy_amount": 5e7},
            {"symbol": "B", "date": date(2024, 1, 2), "buy_amount": 1e7},
        ]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert len(result) == 2

    def test_symbol_preserved(self):
        events = [{"symbol": "600519", "date": date(2024, 1, 1), "buy_amount": 5e7}]
        result = disclosure_event_scoring(events, _make_dims(), {"market_recognition": 1.0})
        assert result[0]["symbol"] == "600519"

    def test_unknown_method_gives_zero(self):
        dims = [{"name": "X", "max_score": 100, "method": "unknown_method", "params": {}}]
        events = [{"symbol": "X", "date": date(2024, 1, 1)}]
        result = disclosure_event_scoring(events, dims, {"X": 1.0})
        assert result[0]["total_score"] == pytest.approx(0.0)

    def test_history_lookup_exception_handled(self):
        dims = [{"name": "h", "max_score": 100, "method": "context", "params": {"field": "x"}}]

        def bad_lookup(sym, dt):
            raise RuntimeError("DB error")

        events = [{"symbol": "X", "date": date(2024, 1, 1)}]
        result = disclosure_event_scoring(events, dims, {"h": 1.0}, history_lookup=bad_lookup)
        assert result[0]["total_score"] == pytest.approx(0.0)

    @pytest.mark.academic_reference
    def test_saaty_ahp_weighted_scoring(self):
        """Saaty AHP (Analytic Hierarchy Process): multi-criteria weighted scoring.

        Two dimensions: market_recognition (weight=0.6) and news_sentiment (weight=0.4).
        Given market_recognition=75, news_sentiment=50, weights={0.6, 0.4}:
        total_score = 75*0.6 + 50*0.4 = 45 + 20 = 65.
        """
        dims = [
            {
                "name": "market_recognition",
                "max_score": 100,
                "method": "direct",
                "params": {"field": "market_recognition", "max": 100},
            },
            {
                "name": "news_sentiment",
                "max_score": 100,
                "method": "direct",
                "params": {"field": "news_sentiment", "max": 100},
            },
        ]
        events = [
            {
                "symbol": "X",
                "date": date(2024, 1, 1),
                "market_recognition": 75,
                "news_sentiment": 50,
            }
        ]
        result = disclosure_event_scoring(
            events, dims, {"market_recognition": 0.6, "news_sentiment": 0.4}
        )
        assert result[0]["total_score"] == pytest.approx(65.0)
