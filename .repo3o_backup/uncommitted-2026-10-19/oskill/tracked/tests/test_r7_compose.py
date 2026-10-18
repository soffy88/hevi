"""Tests for R7 compose skills: trend_signal_compose + mean_reversion_compose."""

from __future__ import annotations

import numpy as np
import pytest

from oskill.mean_reversion_compose import mean_reversion_compose
from oskill.trend_compose import trend_signal_compose

# ──────────────────── Fixtures ────────────────────


@pytest.fixture
def flat_ohlcv():
    n = 300
    close = np.full(n, 100.0)
    return {"high": close + 1.0, "low": close - 1.0, "close": close, "volume": np.ones(n) * 100}


@pytest.fixture
def uptrend_ohlcv():
    n = 300
    close = np.linspace(100, 200, n)
    return {"high": close + 2.0, "low": close - 2.0, "close": close, "volume": np.ones(n) * 500}


@pytest.fixture
def downtrend_ohlcv():
    n = 300
    close = np.linspace(200, 100, n)
    return {"high": close + 2.0, "low": close - 2.0, "close": close, "volume": np.ones(n) * 500}


@pytest.fixture
def sine_ohlcv():
    n = 300
    t = np.arange(n, dtype=float)
    close = 100.0 + 10.0 * np.sin(t * 0.1)
    return {"high": close + 1.5, "low": close - 1.5, "close": close, "volume": np.ones(n) * 200}


@pytest.fixture
def default_trend_config():
    return {
        "indicators": {
            "supertrend": {"enabled": True, "period": 10, "multiplier": 3.0},
            "ema": {"enabled": True, "fast": 20, "slow": 50},
            "adx": {"enabled": True, "period": 14, "threshold": 25.0},
            "macd": {"enabled": True, "fast": 12, "slow": 26, "signal": 9},
        },
        "signal_logic": {"min_confluence": 2, "direction": "both"},
    }


@pytest.fixture
def default_mr_config():
    return {
        "indicators": {
            "vwap": {"enabled": True, "window": 4, "z_threshold": 2.0},
            "bollinger": {"enabled": True, "window": 20, "num_std": 2.0},
            "rsi": {"enabled": True, "period": 14, "oversold": 0.3, "overbought": 0.7},
            "stochastic": {
                "enabled": True,
                "k_period": 14,
                "d_period": 3,
                "smooth_k": 3,
                "oversold": 0.2,
                "overbought": 0.8,
            },
        },
        "signal_logic": {"min_confluence": 2, "direction": "both"},
    }


# ──────────────────── trend_signal_compose ────────────────────


class TestTrendSignalCompose:
    def test_output_shape(self, uptrend_ohlcv, default_trend_config):
        sig = trend_signal_compose(uptrend_ohlcv, config=default_trend_config)
        assert sig.shape == (len(uptrend_ohlcv["close"]),)

    def test_output_values_in_set(self, sine_ohlcv, default_trend_config):
        sig = trend_signal_compose(sine_ohlcv, config=default_trend_config)
        assert set(np.unique(sig)).issubset({-1, 0, 1})

    def test_uptrend_dominated_by_long(self, uptrend_ohlcv, default_trend_config):
        sig = trend_signal_compose(uptrend_ohlcv, config=default_trend_config)
        longs = int(np.sum(sig == 1))
        shorts = int(np.sum(sig == -1))
        assert longs >= shorts, f"uptrend should produce more longs: {longs} vs {shorts}"

    def test_downtrend_dominated_by_short(self, downtrend_ohlcv, default_trend_config):
        sig = trend_signal_compose(downtrend_ohlcv, config=default_trend_config)
        longs = int(np.sum(sig == 1))
        shorts = int(np.sum(sig == -1))
        assert shorts >= longs, f"downtrend should produce more shorts: {shorts} vs {longs}"

    def test_single_indicator_no_confluence(self, uptrend_ohlcv):
        config = {
            "indicators": {
                "ema": {"enabled": True, "fast": 20, "slow": 50},
            },
            "signal_logic": {"min_confluence": 2, "direction": "both"},
        }
        sig = trend_signal_compose(uptrend_ohlcv, config=config)
        # Only 1 indicator active but need 2 → all neutral
        assert np.all(sig == 0)

    def test_long_only_direction(self, sine_ohlcv, default_trend_config):
        cfg = dict(default_trend_config)
        cfg["signal_logic"] = {"min_confluence": 2, "direction": "long"}
        sig = trend_signal_compose(sine_ohlcv, config=cfg)
        assert np.all(sig >= 0), "direction=long should never produce -1"

    def test_short_only_direction(self, sine_ohlcv, default_trend_config):
        cfg = dict(default_trend_config)
        cfg["signal_logic"] = {"min_confluence": 2, "direction": "short"}
        sig = trend_signal_compose(sine_ohlcv, config=cfg)
        assert np.all(sig <= 0), "direction=short should never produce +1"

    def test_disabled_indicators_skipped(self, uptrend_ohlcv):
        config = {
            "indicators": {
                "supertrend": {"enabled": False},
                "ema": {"enabled": True, "fast": 20, "slow": 50},
                "adx": {"enabled": False},
                "macd": {"enabled": True, "fast": 12, "slow": 26, "signal": 9},
            },
            "signal_logic": {"min_confluence": 2, "direction": "both"},
        }
        sig = trend_signal_compose(uptrend_ohlcv, config=config)
        assert sig.shape == (len(uptrend_ohlcv["close"]),)

    def test_empty_indicators_all_neutral(self, uptrend_ohlcv):
        config = {
            "indicators": {
                "supertrend": {"enabled": False},
                "ema": {"enabled": False},
                "adx": {"enabled": False},
                "macd": {"enabled": False},
            },
            "signal_logic": {"min_confluence": 1, "direction": "both"},
        }
        sig = trend_signal_compose(uptrend_ohlcv, config=config)
        assert np.all(sig == 0)

    def test_confluence_1_gives_more_signals(self, uptrend_ohlcv, default_trend_config):
        cfg_c1 = dict(default_trend_config)
        cfg_c1["signal_logic"] = {"min_confluence": 1, "direction": "both"}
        cfg_c2 = dict(default_trend_config)
        cfg_c2["signal_logic"] = {"min_confluence": 3, "direction": "both"}
        sig_c1 = trend_signal_compose(uptrend_ohlcv, config=cfg_c1)
        sig_c2 = trend_signal_compose(uptrend_ohlcv, config=cfg_c2)
        n_nonzero_c1 = int(np.sum(sig_c1 != 0))
        n_nonzero_c2 = int(np.sum(sig_c2 != 0))
        assert n_nonzero_c1 >= n_nonzero_c2


# ──────────────────── mean_reversion_compose ────────────────────


class TestMeanReversionCompose:
    def test_output_shape(self, sine_ohlcv, default_mr_config):
        sig = mean_reversion_compose(sine_ohlcv, config=default_mr_config)
        assert sig.shape == (len(sine_ohlcv["close"]),)

    def test_output_values_in_set(self, sine_ohlcv, default_mr_config):
        sig = mean_reversion_compose(sine_ohlcv, config=default_mr_config)
        assert set(np.unique(sig)).issubset({-1, 0, 1})

    def test_flat_market_mostly_neutral(self, flat_ohlcv, default_mr_config):
        sig = mean_reversion_compose(flat_ohlcv, config=default_mr_config)
        neutral_pct = float(np.mean(sig == 0))
        assert neutral_pct > 0.5, f"flat market should be mostly neutral, got {neutral_pct:.2f}"

    def test_long_only_direction(self, sine_ohlcv, default_mr_config):
        cfg = dict(default_mr_config)
        cfg["signal_logic"] = {"min_confluence": 2, "direction": "long"}
        sig = mean_reversion_compose(sine_ohlcv, config=cfg)
        assert np.all(sig >= 0)

    def test_short_only_direction(self, sine_ohlcv, default_mr_config):
        cfg = dict(default_mr_config)
        cfg["signal_logic"] = {"min_confluence": 2, "direction": "short"}
        sig = mean_reversion_compose(sine_ohlcv, config=cfg)
        assert np.all(sig <= 0)

    def test_disabled_vwap(self, sine_ohlcv, default_mr_config):
        cfg = {
            "indicators": {
                "vwap": {"enabled": False},
                "bollinger": {"enabled": True, "window": 20, "num_std": 2.0},
                "rsi": {"enabled": True, "period": 14, "oversold": 0.3, "overbought": 0.7},
                "stochastic": {"enabled": False},
            },
            "signal_logic": {"min_confluence": 2, "direction": "both"},
        }
        sig = mean_reversion_compose(sine_ohlcv, config=cfg)
        assert sig.shape == (len(sine_ohlcv["close"]),)

    def test_low_threshold_more_signals(self, sine_ohlcv):
        cfg_tight = {
            "indicators": {
                "rsi": {"enabled": True, "period": 14, "oversold": 0.45, "overbought": 0.55},
                "bollinger": {"enabled": True, "window": 20, "num_std": 0.5},
                "vwap": {"enabled": False},
                "stochastic": {"enabled": False},
            },
            "signal_logic": {"min_confluence": 1, "direction": "both"},
        }
        cfg_wide = {
            "indicators": {
                "rsi": {"enabled": True, "period": 14, "oversold": 0.1, "overbought": 0.9},
                "bollinger": {"enabled": True, "window": 20, "num_std": 3.0},
                "vwap": {"enabled": False},
                "stochastic": {"enabled": False},
            },
            "signal_logic": {"min_confluence": 1, "direction": "both"},
        }
        sig_tight = mean_reversion_compose(sine_ohlcv, config=cfg_tight)
        sig_wide = mean_reversion_compose(sine_ohlcv, config=cfg_wide)
        assert int(np.sum(sig_tight != 0)) >= int(np.sum(sig_wide != 0))

    def test_empty_indicators_all_neutral(self, sine_ohlcv):
        config = {
            "indicators": {
                "vwap": {"enabled": False},
                "bollinger": {"enabled": False},
                "rsi": {"enabled": False},
                "stochastic": {"enabled": False},
            },
            "signal_logic": {"min_confluence": 1, "direction": "both"},
        }
        sig = mean_reversion_compose(sine_ohlcv, config=config)
        assert np.all(sig == 0)

    def test_high_confluence_fewer_signals(self, sine_ohlcv, default_mr_config):
        cfg_c1 = dict(default_mr_config)
        cfg_c1["signal_logic"] = {"min_confluence": 1, "direction": "both"}
        cfg_c4 = dict(default_mr_config)
        cfg_c4["signal_logic"] = {"min_confluence": 4, "direction": "both"}
        sig_c1 = mean_reversion_compose(sine_ohlcv, config=cfg_c1)
        sig_c4 = mean_reversion_compose(sine_ohlcv, config=cfg_c4)
        assert int(np.sum(sig_c1 != 0)) >= int(np.sum(sig_c4 != 0))
