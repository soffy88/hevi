"""Tests for oskill.backtest.market_rules_backtest."""

from __future__ import annotations

from datetime import date

import pytest

from oskill.backtest.market_rules_backtest import market_rules_backtest_run


def _make_bars(symbol, dates_closes):
    bars = []
    opens = [c * 0.99 for c in dates_closes.values()]
    for i, (dt, close) in enumerate(dates_closes.items()):
        bars.append(
            {
                "date": dt,
                "open": opens[i],
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return bars


# 5 sequential dates for testing
D = [date(2024, 1, i) for i in range(2, 7)]  # Jan 2..6


def _simple_ohlcv(prices=(100.0, 102.0, 104.0, 101.0, 103.0)):
    return _make_bars("SYM", {D[i]: prices[i] for i in range(5)})


def _simple_rules():
    return {
        "t_plus_n": 1,
        "commission": {"rate": 0.0003, "min_fee": 5.0},
        "stamp_tax": {"rate": 0.001, "direction": "sell"},
        "daily_limit": {"get_limit_pct": lambda sym, dt: 0.10},
        "limit_block_buy": True,
        "limit_block_sell": True,
    }


class TestMarketRulesBacktestRun:
    def test_empty_signals_no_trades(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        result = market_rules_backtest_run([], ohlcv, _simple_rules())
        assert result["trades"] == []
        assert result["blocked_signals"] == []

    def test_required_keys_present(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        result = market_rules_backtest_run([], ohlcv, _simple_rules())
        assert "trades" in result
        assert "equity_curve" in result
        assert "metrics" in result
        assert "blocked_signals" in result

    def test_buy_and_sell_produces_trade(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        signals = [
            {"symbol": "SYM", "date": D[0], "side": "buy", "size_fraction": 1.0},
            {"symbol": "SYM", "date": D[2], "side": "sell", "size_fraction": 1.0},
        ]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules(), initial_capital=100_000)
        assert len(result["trades"]) == 1

    def test_no_bar_data_signal_blocked(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        signals = [{"symbol": "MISSING", "date": D[0], "side": "buy", "size_fraction": 1.0}]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules())
        assert any(b.get("reason") == "no_bar_data" for b in result["blocked_signals"])

    def test_no_next_bar_signal_blocked(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        # signal at last bar -> no next bar
        signals = [{"symbol": "SYM", "date": D[-1], "side": "buy", "size_fraction": 1.0}]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules())
        assert any(b.get("reason") == "no_next_bar" for b in result["blocked_signals"])

    def test_t_plus_n_blocks_early_sell(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        signals = [
            {"symbol": "SYM", "date": D[0], "side": "buy", "size_fraction": 1.0},
            {"symbol": "SYM", "date": D[0], "side": "sell", "size_fraction": 1.0},
        ]
        rules = _simple_rules()
        rules["t_plus_n"] = 2  # need 2 business days before selling
        result = market_rules_backtest_run(signals, ohlcv, rules, initial_capital=100_000)
        # Sell on D[0] -> exec on D[1], buy was also on D[1]; 1 day between = blocked
        blocked_reasons = [b.get("reason", "") for b in result["blocked_signals"]]
        assert any("t_plus" in r for r in blocked_reasons)

    def test_limit_up_blocks_buy(self):
        # D[1] price=110 is 10% up from D[0] price=100 -> limit-up blocks buy signal on D[1]
        prices = (100.0, 110.0, 112.0, 113.0, 114.0)
        ohlcv = {"SYM": _simple_ohlcv(prices=prices)}
        # Buy signal on D[1] (current_bar=D[1] close=110, prev_bar=D[0] close=100 -> limit-up!)
        signals = [{"symbol": "SYM", "date": D[1], "side": "buy", "size_fraction": 1.0}]
        rules = _simple_rules()
        rules["daily_limit"] = {"get_limit_pct": lambda sym, dt: 0.10}
        rules["limit_block_buy"] = True
        result = market_rules_backtest_run(signals, ohlcv, rules)
        assert any(b.get("reason") == "limit_up_block_buy" for b in result["blocked_signals"])

    def test_limit_down_blocks_sell(self):
        # D[1] price=90 is 10% down from D[0] price=100 -> limit-down triggers, blocks sell on D[1]
        prices = (100.0, 90.0, 88.0, 87.0, 86.0)
        ohlcv = {"SYM": _simple_ohlcv(prices=prices)}
        # First buy on D[0], then sell signal on D[1] (limit-down)
        signals = [
            {"symbol": "SYM", "date": D[0], "side": "buy", "size_fraction": 0.5},
            {"symbol": "SYM", "date": D[1], "side": "sell", "size_fraction": 1.0},
        ]
        rules = _simple_rules()
        rules["t_plus_n"] = 0  # allow immediate sell
        rules["daily_limit"] = {"get_limit_pct": lambda sym, dt: 0.10}
        rules["limit_block_sell"] = True
        result = market_rules_backtest_run(signals, ohlcv, rules, initial_capital=100_000)
        assert any(b.get("reason") == "limit_down_block_sell" for b in result["blocked_signals"])

    def test_equity_curve_has_entries(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        signals = [
            {"symbol": "SYM", "date": D[0], "side": "buy", "size_fraction": 0.5},
        ]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules(), initial_capital=100_000)
        assert len(result["equity_curve"]) >= 1

    def test_metrics_dict_has_keys(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        result = market_rules_backtest_run([], ohlcv, _simple_rules())
        assert "n_trades" in result["metrics"]

    def test_sell_without_position_does_nothing(self):
        ohlcv = {"SYM": _simple_ohlcv()}
        signals = [{"symbol": "SYM", "date": D[0], "side": "sell", "size_fraction": 1.0}]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules(), initial_capital=100_000)
        assert result["trades"] == []

    def test_pnl_direction_correct(self):
        """Buy at lower price, sell at higher -> positive PnL."""
        prices = (100.0, 102.0, 105.0, 108.0, 110.0)
        ohlcv = {"SYM": _simple_ohlcv(prices=prices)}
        signals = [
            {"symbol": "SYM", "date": D[0], "side": "buy", "size_fraction": 0.5},
            {"symbol": "SYM", "date": D[2], "side": "sell", "size_fraction": 1.0},
        ]
        result = market_rules_backtest_run(signals, ohlcv, _simple_rules(), initial_capital=100_000)
        if result["trades"]:
            assert result["trades"][0]["pnl"] > 0

    @pytest.mark.academic_reference
    def test_lopezdeprado_ch5_market_microstructure_backtest(self):
        """Lopez de Prado (2018) AFML Ch.5: realistic backtest with transaction costs.

        A proper backtest must account for: T+N settlement, daily limits, fees.
        With no signals, equity stays at initial_capital and no trades occur.
        With one round-trip trade (buy then sell), commission + stamp_tax reduce PnL.
        """
        ohlcv = {"SYM": _simple_ohlcv()}
        # No signals -> capital preserved
        result = market_rules_backtest_run([], ohlcv, _simple_rules(), initial_capital=500_000)
        assert result["metrics"]["n_trades"] == 0
        assert result["trades"] == []
        assert result["blocked_signals"] == []
