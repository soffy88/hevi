"""Tests for dollar_bar_aggregation, volume_imbalance_bar, tick_imbalance_bar."""

import numpy as np
import pandas as pd
import pytest

from oskill.microstructure.bar_aggregation import (
    dollar_bar_aggregation,
    tick_imbalance_bar,
    volume_imbalance_bar,
)


def make_ticks(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    prices = 100 + np.cumsum(rng.normal(0, 0.1, n))
    volumes = rng.integers(10, 100, n).astype(float)
    return pd.DataFrame({"timestamp": np.arange(n), "price": prices, "volume": volumes})


# ---- dollar_bar_aggregation ----


class TestDollarBarAggregation:
    def test_returns_dataframe(self):
        ticks = make_ticks(200)
        bars = dollar_bar_aggregation(ticks, dollar_threshold=5000.0)
        assert isinstance(bars, pd.DataFrame)

    def test_columns_present(self):
        ticks = make_ticks(200)
        bars = dollar_bar_aggregation(ticks, dollar_threshold=5000.0)
        expected = {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "dollar_volume",
            "tick_count",
            "timestamp_start",
            "timestamp_end",
        }
        assert expected.issubset(set(bars.columns))

    def test_dollar_threshold_respected(self):
        """Each bar's dollar_volume should be >= threshold (last bar may be partial if no open bar)."""
        ticks = make_ticks(500)
        threshold = 8000.0
        bars = dollar_bar_aggregation(ticks, dollar_threshold=threshold)
        # All closed bars must have dollar_volume >= threshold
        if len(bars) > 0:
            assert (bars["dollar_volume"] >= threshold).all()

    def test_ohlc_correct(self):
        """High >= Open >= Low; High >= Close >= Low."""
        ticks = make_ticks(200)
        bars = dollar_bar_aggregation(ticks, dollar_threshold=3000.0)
        if len(bars) == 0:
            pytest.skip("No bars formed")
        assert (bars["high"] >= bars["open"]).all()
        assert (bars["high"] >= bars["close"]).all()
        assert (bars["low"] <= bars["open"]).all()
        assert (bars["low"] <= bars["close"]).all()

    def test_empty_input_returns_empty(self):
        empty = pd.DataFrame(columns=["timestamp", "price", "volume"])
        bars = dollar_bar_aggregation(empty, dollar_threshold=1000.0)
        assert isinstance(bars, pd.DataFrame)
        assert len(bars) == 0

    def test_multiple_bars_formed(self):
        """With low threshold, multiple bars should form."""
        ticks = make_ticks(500)
        bars = dollar_bar_aggregation(ticks, dollar_threshold=500.0)
        assert len(bars) > 1

    def test_tick_count_positive(self):
        ticks = make_ticks(200)
        bars = dollar_bar_aggregation(ticks, dollar_threshold=3000.0)
        if len(bars) > 0:
            assert (bars["tick_count"] > 0).all()

    def test_custom_column_mapping(self):
        """Custom column names via columns dict."""
        rng = np.random.default_rng(5)
        ticks = pd.DataFrame(
            {
                "ts": np.arange(100),
                "px": 100 + np.cumsum(rng.normal(0, 0.1, 100)),
                "qty": rng.integers(10, 100, 100).astype(float),
            }
        )
        bars = dollar_bar_aggregation(
            ticks,
            dollar_threshold=2000.0,
            columns={"price": "px", "volume": "qty", "timestamp": "ts"},
        )
        assert isinstance(bars, pd.DataFrame)


# ---- volume_imbalance_bar ----


class TestVolumeImbalanceBar:
    def test_returns_dataframe(self):
        ticks = make_ticks(200)
        bars = volume_imbalance_bar(ticks, static_threshold=50.0)
        assert isinstance(bars, pd.DataFrame)

    def test_columns_present(self):
        ticks = make_ticks(200)
        bars = volume_imbalance_bar(ticks, static_threshold=50.0)
        expected = {"open", "high", "low", "close", "volume"}
        assert expected.issubset(set(bars.columns))

    def test_static_threshold_forms_bars(self):
        ticks = make_ticks(300)
        bars = volume_imbalance_bar(ticks, static_threshold=30.0)
        assert len(bars) >= 1

    def test_empty_input_returns_empty(self):
        empty = pd.DataFrame(columns=["timestamp", "price", "volume"])
        bars = volume_imbalance_bar(empty, static_threshold=100.0)
        assert isinstance(bars, pd.DataFrame)
        assert len(bars) == 0

    def test_ohlc_valid(self):
        ticks = make_ticks(200)
        bars = volume_imbalance_bar(ticks, static_threshold=30.0)
        if len(bars) == 0:
            pytest.skip("No bars formed")
        assert (bars["high"] >= bars["open"]).all()
        assert (bars["high"] >= bars["close"]).all()
        assert (bars["low"] <= bars["open"]).all()
        assert (bars["low"] <= bars["close"]).all()

    def test_ewma_method_forms_bars(self):
        ticks = make_ticks(500)
        bars = volume_imbalance_bar(ticks, expected_imbalance_method="ewma", ewma_window=20)
        assert len(bars) >= 1

    def test_volume_positive(self):
        ticks = make_ticks(200)
        bars = volume_imbalance_bar(ticks, static_threshold=30.0)
        if len(bars) > 0:
            assert (bars["volume"] > 0).all()

    def test_tick_count_positive(self):
        ticks = make_ticks(200)
        bars = volume_imbalance_bar(ticks, static_threshold=30.0)
        if len(bars) > 0:
            assert (bars["tick_count"] > 0).all()


# ---- tick_imbalance_bar ----


class TestTickImbalanceBar:
    def test_returns_dataframe(self):
        ticks = make_ticks(200)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        assert isinstance(bars, pd.DataFrame)

    def test_columns_present(self):
        ticks = make_ticks(200)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        expected = {"open", "high", "low", "close", "volume"}
        assert expected.issubset(set(bars.columns))

    def test_static_threshold_forms_bars(self):
        ticks = make_ticks(300)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        assert len(bars) >= 1

    def test_empty_input_returns_empty(self):
        empty = pd.DataFrame(columns=["timestamp", "price", "volume"])
        bars = tick_imbalance_bar(empty, static_threshold=5.0)
        assert isinstance(bars, pd.DataFrame)
        assert len(bars) == 0

    def test_ohlc_valid(self):
        ticks = make_ticks(200)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        if len(bars) == 0:
            pytest.skip("No bars formed")
        assert (bars["high"] >= bars["open"]).all()
        assert (bars["high"] >= bars["close"]).all()
        assert (bars["low"] <= bars["open"]).all()
        assert (bars["low"] <= bars["close"]).all()

    def test_ewma_method_forms_bars(self):
        ticks = make_ticks(500)
        bars = tick_imbalance_bar(ticks, expected_imbalance_method="ewma", ewma_window=20)
        assert len(bars) >= 1

    def test_volume_positive(self):
        ticks = make_ticks(200)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        if len(bars) > 0:
            assert (bars["volume"] > 0).all()

    def test_tick_count_positive(self):
        ticks = make_ticks(200)
        bars = tick_imbalance_bar(ticks, static_threshold=5.0)
        if len(bars) > 0:
            assert (bars["tick_count"] > 0).all()
