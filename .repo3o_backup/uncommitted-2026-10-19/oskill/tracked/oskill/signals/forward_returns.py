"""Forward return analytics for event-driven backtests."""

from __future__ import annotations

import statistics

import oprim

STABILITY = "experimental"


def aggregate_signal_returns(
    events: list[dict],
    periods: list[int],
) -> dict:
    """Aggregate forward returns across multiple periods for a list of signal events.

    Parameters
    ----------
    events : list of {"event_date": date, "entry_price": float,
                       "forward_returns": {period: ret}}
             Each event must have forward_returns for each period in `periods`.
    periods : list of forward periods (e.g. [5, 10, 20])

    Returns
    -------
    {
        "n_events": int,
        "by_period": {
            period: {
                "mean": float, "median": float, "std": float,
                "win_rate": float, "p25": float, "p75": float,
                "max_drawdown": float
            }
        }
    }

    Methodology
    -----------
    Standard event-driven backtest summary statistics. For each period,
    computes win rate (proportion > 0), distribution percentiles, and
    max drawdown of cumulative event returns.

    Uses: oprim.statistics.percentile_value, oprim.statistics.distribution_summary

    Reference
    ---------
    Lopez de Prado, M. (2018). Advances in Financial Machine Learning, Ch. 4.
    """
    if not events:
        return {"n_events": 0, "by_period": {p: _empty_period_stats() for p in periods}}

    if not periods:
        return {"n_events": len(events), "by_period": {}}

    by_period: dict[int, dict] = {}

    for period in periods:
        rets = []
        for ev in events:
            fwd = ev.get("forward_returns", {})
            if period in fwd:
                rets.append(float(fwd[period]))

        if not rets:
            by_period[period] = _empty_period_stats()
            continue

        rets_sorted = sorted(rets)
        mean_ret = sum(rets) / len(rets)
        median_ret = oprim.percentile_value(rets_sorted, q=0.5)
        std_ret = statistics.stdev(rets) if len(rets) > 1 else 0.0
        win_rate = sum(1 for r in rets if r > 0) / len(rets)
        p25 = oprim.percentile_value(rets_sorted, q=0.25)
        p75 = oprim.percentile_value(rets_sorted, q=0.75)

        # Max drawdown of cumulative event returns (ordered as they appear)
        cum_rets = []
        cum = 0.0
        for r in rets:
            cum += r
            cum_rets.append(cum)
        peak = cum_rets[0]
        max_dd = 0.0
        for v in cum_rets:
            if v > peak:
                peak = v
            dd = peak - v
            if dd > max_dd:
                max_dd = dd

        by_period[period] = {
            "mean": mean_ret,
            "median": median_ret,
            "std": std_ret,
            "win_rate": win_rate,
            "p25": p25,
            "p75": p75,
            "max_drawdown": max_dd,
        }

    return {"n_events": len(events), "by_period": by_period}


def _empty_period_stats() -> dict:
    return {
        "mean": 0.0,
        "median": 0.0,
        "std": 0.0,
        "win_rate": 0.0,
        "p25": 0.0,
        "p75": 0.0,
        "max_drawdown": 0.0,
    }
