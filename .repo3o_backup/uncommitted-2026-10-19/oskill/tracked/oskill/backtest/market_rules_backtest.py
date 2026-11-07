"""Backtest engine with market-specific rules (daily limits / T+N / fees)."""

from __future__ import annotations

from datetime import date

import oprim

STABILITY = "experimental"


def market_rules_backtest_run(
    signals: list[dict],
    ohlcv_by_symbol: dict[str, list[dict]],
    market_rules: dict,
    initial_capital: float = 1_000_000,
) -> dict:
    """Run a backtest with realistic market rules applied.

    Parameters
    ----------
    signals : list of {"symbol": str, "date": date, "side": "buy"/"sell",
                       "size_fraction": float} signal events
    ohlcv_by_symbol : {symbol: [{"date": date, "open": float, "high": float,
                                  "low": float, "close": float, "volume": float}, ...]}
    market_rules : {
        "daily_limit": {"get_limit_pct": callable(symbol, date) -> float},
        "t_plus_n": int,    # e.g. 1 for A-share
        "commission": {"rate": float, "min_fee": float},
        "stamp_tax": {"rate": float, "direction": "buy"/"sell"/"both"},
        "limit_block_buy": bool,  # block buys at limit-up
        "limit_block_sell": bool, # block sells at limit-down
    }
    initial_capital : starting capital

    Returns
    -------
    {
        "trades": list[dict],
        "equity_curve": list[tuple[date, float]],
        "metrics": dict,   # from portfolio_metrics_summary
        "blocked_signals": list[dict]   # signals not executable due to market rules
    }

    Methodology
    -----------
    For each signal, check market rule constraints (T+N, daily limit, etc.)
    using oprim.markets.* primitives. Execute valid signals at next-bar open.
    Track full PnL with fees and tax.

    Uses: oprim.markets.limits, oprim.markets.rules,
          oskill.performance.portfolio_metrics_summary

    Reference
    ---------
    Realistic backtest framework patterns; Lopez de Prado Ch. 5.
    """
    from oskill.performance import portfolio_metrics_summary

    cash = initial_capital
    positions: dict[str, dict] = {}  # symbol -> {qty, entry_price, entry_date}
    trades: list[dict] = []
    blocked_signals: list[dict] = []
    equity_records: list[tuple] = []

    t_plus_n = market_rules.get("t_plus_n", 1)
    commission_rules = market_rules.get("commission", {"rate": 0.0, "min_fee": 0.0})
    stamp_tax_rules = market_rules.get("stamp_tax", {"rate": 0.0, "direction": "sell"})
    daily_limit_rules = market_rules.get("daily_limit", {})
    limit_block_buy = market_rules.get("limit_block_buy", True)
    limit_block_sell = market_rules.get("limit_block_sell", True)
    get_limit_pct = daily_limit_rules.get("get_limit_pct", lambda sym, dt: 0.1)

    sorted_signals = sorted(signals, key=lambda s: s.get("date", date.min))

    def _get_bar(symbol: str, bar_date: date) -> dict | None:
        bars = ohlcv_by_symbol.get(symbol, [])
        for b in bars:
            if b.get("date") == bar_date:
                return b
        return None

    def _get_prev_bar(symbol: str, signal_date: date) -> dict | None:
        bars = ohlcv_by_symbol.get(symbol, [])
        sorted_bars = sorted(bars, key=lambda b: b.get("date", date.min))
        for i, b in enumerate(sorted_bars):
            if b.get("date") == signal_date and i > 0:
                return sorted_bars[i - 1]
        return None

    def _get_next_bar(symbol: str, signal_date: date) -> dict | None:
        bars = ohlcv_by_symbol.get(symbol, [])
        sorted_bars = sorted(bars, key=lambda b: b.get("date", date.min))
        for i, b in enumerate(sorted_bars):
            if b.get("date") == signal_date and i + 1 < len(sorted_bars):
                return sorted_bars[i + 1]
        return None

    processed_dates: set[date] = set()

    for sig in sorted_signals:
        symbol = sig.get("symbol", "")
        sig_date = sig.get("date", date.min)
        side = sig.get("side", "buy")
        size_fraction = float(sig.get("size_fraction", 1.0))

        current_bar = _get_bar(symbol, sig_date)
        if current_bar is None:
            blocked_signals.append({**sig, "reason": "no_bar_data"})
            continue

        exec_bar = _get_next_bar(symbol, sig_date)
        if exec_bar is None:
            blocked_signals.append({**sig, "reason": "no_next_bar"})
            continue

        exec_date = exec_bar.get("date")
        exec_price = exec_bar.get("open", current_bar.get("close", 0.0))
        prev_bar = _get_prev_bar(symbol, sig_date)
        prev_close = prev_bar.get("close", 0.0) if prev_bar is not None else 0.0

        limit_pct = get_limit_pct(symbol, sig_date)

        if side == "buy" and limit_block_buy:
            if prev_close > 0 and oprim.detect_daily_limit_up(
                close_price=current_bar.get("close", 0.0),
                prev_close=prev_close,
                limit_pct=limit_pct,
            ):
                blocked_signals.append({**sig, "reason": "limit_up_block_buy"})
                continue

        if side == "sell" and limit_block_sell:
            if prev_close > 0 and oprim.detect_daily_limit_down(
                close_price=current_bar.get("close", 0.0),
                prev_close=prev_close,
                limit_pct=limit_pct,
            ):
                blocked_signals.append({**sig, "reason": "limit_down_block_sell"})
                continue

        if side == "sell" and symbol in positions:
            pos = positions[symbol]
            if oprim.t_plus_n_blocked(
                entry_date=pos["entry_date"], current_date=exec_date, t_plus_n=t_plus_n
            ):
                blocked_signals.append({**sig, "reason": f"t_plus_{t_plus_n}_blocked"})
                continue

        if side == "buy":
            trade_amount = cash * size_fraction
            fee = oprim.compute_commission(
                trade_amount=trade_amount,
                rate=commission_rules["rate"],
                min_fee=commission_rules.get("min_fee", 0.0),
            )
            tax_dir = stamp_tax_rules.get("direction", "sell")
            tax = (
                oprim.compute_stamp_tax(
                    trade_amount=trade_amount, rate=stamp_tax_rules["rate"], direction=tax_dir
                )
                if tax_dir in ("buy", "both")
                else 0.0
            )
            total_cost = trade_amount + fee + tax
            qty = trade_amount / exec_price if exec_price > 0 else 0

            cash -= total_cost
            positions[symbol] = {
                "qty": qty,
                "entry_price": exec_price,
                "entry_date": exec_date,
                "entry_cost": fee + tax,
            }

        elif side == "sell" and symbol in positions:
            pos = positions[symbol]
            qty = pos["qty"]
            trade_amount = qty * exec_price
            fee = oprim.compute_commission(
                trade_amount=trade_amount,
                rate=commission_rules["rate"],
                min_fee=commission_rules.get("min_fee", 0.0),
            )
            tax_dir = stamp_tax_rules.get("direction", "sell")
            tax = (
                oprim.compute_stamp_tax(
                    trade_amount=trade_amount, rate=stamp_tax_rules["rate"], direction=tax_dir
                )
                if tax_dir in ("sell", "both")
                else 0.0
            )
            net_proceeds = trade_amount - fee - tax
            pnl = net_proceeds - (qty * pos["entry_price"]) - pos.get("entry_cost", 0.0)
            pnl_pct = pnl / (qty * pos["entry_price"]) if pos["entry_price"] > 0 else 0.0

            cash += net_proceeds
            trades.append(
                {
                    "symbol": symbol,
                    "entry_date": pos["entry_date"],
                    "exit_date": exec_date,
                    "entry_price": pos["entry_price"],
                    "exit_price": exec_price,
                    "qty": qty,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "fees": fee + tax,
                }
            )
            del positions[symbol]

        if exec_date not in processed_dates:
            position_value = sum(
                p["qty"] * (ohlcv_by_symbol.get(sym, [{}])[-1].get("close", p["entry_price"]))
                for sym, p in positions.items()
            )
            equity_records.append((exec_date, cash + position_value))
            processed_dates.add(exec_date)

    equity_curve = sorted(equity_records, key=lambda x: x[0])
    if not equity_curve:
        equity_curve = [(date.today(), initial_capital)]

    metrics = portfolio_metrics_summary(trades, equity_curve, initial_capital)

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "metrics": metrics,
        "blocked_signals": blocked_signals,
    }
