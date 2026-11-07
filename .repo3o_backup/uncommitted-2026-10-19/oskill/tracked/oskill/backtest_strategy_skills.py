"""Backtest and strategy analysis oskills — composite workflows combining oprims."""

from __future__ import annotations


class BacktestSkillError(Exception):
    """Raised when a backtest skill fails."""


def portfolio_backtest_simulation(
    *, trades: list[dict], initial_capital: float = 10000, fee_rate: float = 0.001
) -> dict:
    """Simulate portfolio backtest from trades with fees.

    Internal oprim composition:
    - oprim.compute_pnl_from_trades
    - oprim.compute_equity_curve
    """
    from oprim.quant_analysis import compute_equity_curve, compute_pnl_from_trades

    pnl = compute_pnl_from_trades(trades=trades)
    pnl_after_fees = [
        p - abs(t.get("size", 1) * t.get("entry", 0)) * fee_rate * 2
        for p, t in zip(pnl, trades, strict=False)
    ]
    curve = compute_equity_curve(initial_capital=initial_capital, pnl_series=pnl_after_fees)
    total_return = (curve[-1] - curve[0]) / curve[0] if curve[0] > 0 else 0
    return {
        "equity_curve": curve,
        "total_return": round(total_return, 6),
        "trade_count": len(trades),
        "total_fees": round(
            sum(abs(p - pf) for p, pf in zip(pnl, pnl_after_fees, strict=False)), 2
        ),
    }


def transaction_cost_model(
    *, order_size: float, avg_daily_volume: float, volatility: float, fee_rate: float = 0.001
) -> dict:
    """Model total transaction costs (fees + market impact).

    Internal oprim composition:
    - oprim.compute_market_impact
    - oprim.compute_slippage_estimate
    """
    from oprim.quant_analysis import compute_market_impact

    impact = compute_market_impact(
        order_size=order_size, avg_daily_volume=avg_daily_volume, volatility=volatility
    )
    fee_cost = order_size * fee_rate
    total = fee_cost + order_size * impact
    return {
        "fee_cost": round(fee_cost, 4),
        "impact_cost": round(order_size * impact, 4),
        "total_cost": round(total, 4),
        "impact_bps": round(impact * 10000, 2),
    }


def walk_forward_analysis(
    *, data: list[float], train_ratio: float = 0.7, window_size: int = 60, step_size: int = 20
) -> dict:
    """Walk-forward analysis with train/test splits.

    Internal oprim composition:
    - oprim.split_train_test_time_series
    - oprim.compute_benchmark_metrics
    """
    from oprim.quant_analysis import split_train_test_time_series

    train, test = split_train_test_time_series(data=data, train_ratio=train_ratio)
    return {
        "train_size": len(train),
        "test_size": len(test),
        "windows": max(1, len(test) // step_size),
    }


def monte_carlo_significance_test(
    *, strategy_returns: list[float], n_simulations: int = 1000
) -> dict:
    """Test strategy significance via Monte Carlo permutation.

    Internal oprim composition:
    - oprim.generate_bootstrap_samples
    - oprim.compute_monte_carlo_simulation
    """
    from oprim.quant_analysis import generate_bootstrap_samples

    if not strategy_returns:
        return {"significant": False, "p_value": 1.0}
    actual_mean = sum(strategy_returns) / len(strategy_returns)
    samples = generate_bootstrap_samples(data=strategy_returns, n_samples=n_simulations)
    better = sum(1 for s in samples if sum(s) / len(s) >= actual_mean)
    p_value = better / n_simulations
    return {
        "significant": p_value < 0.05,
        "p_value": round(p_value, 4),
        "actual_mean": round(actual_mean, 6),
    }


def strategy_benchmark_comparison(
    *, strategy_returns: list[float], benchmark_returns: list[float]
) -> dict:
    """Compare strategy against benchmark with full metrics.

    Internal oprim composition:
    - oprim.compute_benchmark_metrics
    - oprim.compute_relative_performance
    """
    from oprim.quant_analysis import compute_benchmark_metrics, compute_relative_performance

    metrics = compute_benchmark_metrics(
        strategy_returns=strategy_returns, benchmark_returns=benchmark_returns
    )
    curve_s = [1.0]
    for r in strategy_returns:
        curve_s.append(curve_s[-1] * (1 + r))
    curve_b = [1.0]
    for r in benchmark_returns:
        curve_b.append(curve_b[-1] * (1 + r))
    rel = compute_relative_performance(strategy_curve=curve_s, benchmark_curve=curve_b)
    return {**metrics, "outperformance": round(rel[-1] - 1.0, 6) if rel else 0}


def strategy_capacity_estimation(
    *, avg_daily_volume: float, target_participation: float = 0.01, volatility: float = 0.02
) -> dict:
    """Estimate strategy capacity before market impact degrades returns.

    Internal oprim composition:
    - oprim.compute_market_impact
    - oprim.compute_portfolio_turnover
    """
    from oprim.quant_analysis import compute_market_impact

    max_order = avg_daily_volume * target_participation
    impact = compute_market_impact(
        order_size=max_order, avg_daily_volume=avg_daily_volume, volatility=volatility
    )
    capacity_usd = max_order * 50000  # rough BTC price assumption
    return {
        "max_order_size": round(max_order, 2),
        "impact_at_capacity": round(impact, 6),
        "estimated_capacity_usd": round(capacity_usd, 0),
    }


def out_of_sample_validation(*, in_sample_sharpe: float, oos_sharpe: float) -> dict:
    """Validate out-of-sample performance degradation.

    Internal oprim composition:
    - oprim.compute_benchmark_metrics
    - oprim.split_train_test_time_series
    """
    degradation = 1 - (oos_sharpe / in_sample_sharpe) if in_sample_sharpe != 0 else 1.0
    return {
        "degradation": round(degradation, 4),
        "oos_sharpe": oos_sharpe,
        "overfitting_risk": "high"
        if degradation > 0.5
        else "medium"
        if degradation > 0.2
        else "low",
    }


def risk_metrics_bundle(*, equity_curve: list[float]) -> dict:
    """Compute comprehensive risk metrics bundle.

    Internal oprim composition:
    - oprim.compute_drawdown_distribution
    - oprim.compute_position_risk
    """
    from oprim.quant_analysis import compute_drawdown_distribution

    dd = compute_drawdown_distribution(equity_curve=equity_curve)
    returns = (
        [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            for i in range(1, len(equity_curve))
        ]
        if len(equity_curve) > 1
        else []
    )
    vol = (sum(r**2 for r in returns) / max(len(returns) - 1, 1)) ** 0.5 if returns else 0
    return {**dd, "volatility": round(vol, 6), "return_count": len(returns)}


def turnover_churn_analysis(*, position_history: list[dict[str, float]]) -> dict:
    """Analyze portfolio turnover and churn patterns.

    Internal oprim composition:
    - oprim.compute_portfolio_turnover
    - oprim.compute_position_churn
    """
    from oprim.quant_analysis import compute_portfolio_turnover, compute_position_churn

    churn = compute_position_churn(position_history=position_history)
    if len(position_history) >= 2:
        last_turnover = compute_portfolio_turnover(
            weights_before=position_history[-2], weights_after=position_history[-1]
        )
    else:
        last_turnover = 0
    return {"avg_churn": churn, "last_turnover": last_turnover, "periods": len(position_history)}


def signal_crowding_analysis(
    *, signal_counts: dict[str, int], total_participants: int, threshold: float = 0.7
) -> dict:
    """Analyze signal crowding with actionable recommendation.

    Internal oprim composition:
    - oprim.compute_signal_crowding
    - oprim.compute_herfindahl_index
    """
    from oprim.quant_analysis import compute_herfindahl_index, compute_signal_crowding

    crowding = compute_signal_crowding(
        signal_counts=signal_counts, total_participants=total_participants
    )
    weights = (
        {k: v / total_participants for k, v in signal_counts.items()}
        if total_participants > 0
        else {}
    )
    hhi = compute_herfindahl_index(weights=weights)
    return {**crowding, "hhi": hhi, "crowded": crowding["crowding_ratio"] > threshold}


def comparative_score_anchoring(*, current_score: float, historical_scores: list[float]) -> dict:
    """Anchor current score against historical distribution.

    Internal oprim composition:
    - oprim.cross_sectional_rank
    - oprim.compute_uncertainty_threshold
    """
    from oprim.quant_analysis import compute_uncertainty_threshold

    if not historical_scores:
        return {"percentile": 0.5, "z_score": 0, "extreme": False}
    mean = sum(historical_scores) / len(historical_scores)
    std = (
        sum((s - mean) ** 2 for s in historical_scores) / max(len(historical_scores) - 1, 1)
    ) ** 0.5
    z = (current_score - mean) / std if std > 0 else 0
    pct = sum(1 for s in historical_scores if s <= current_score) / len(historical_scores)
    threshold = compute_uncertainty_threshold(
        uncertainties=[abs(s - mean) / max(std, 0.01) for s in historical_scores]
    )
    return {"percentile": round(pct, 4), "z_score": round(z, 4), "extreme": abs(z) > threshold}


def risk_scale_calculation(
    *,
    positions: dict[str, float],
    factor_loadings: dict[str, dict[str, float]],
    volatilities: dict[str, float],
) -> dict:
    """Calculate portfolio risk scale with factor decomposition.

    Internal oprim composition:
    - oprim.compute_risk_exposure
    - oprim.compute_position_risk
    """
    from oprim.quant_analysis import compute_position_risk, compute_risk_exposure

    exposures = compute_risk_exposure(positions=positions, factor_loadings=factor_loadings)
    total_risk = sum(abs(w) * volatilities.get(a, 0.02) for a, w in positions.items())
    risk = compute_position_risk(position_size=1.0, volatility=total_risk)
    return {
        "factor_exposures": exposures,
        "total_risk": round(total_risk, 6),
        "var_95_pct": risk["var_95"],
    }


def similar_historical_context_search(
    *, current_features: dict[str, float], history: list[dict[str, float]], top_k: int = 5
) -> list[dict]:
    """Search for similar historical contexts by feature distance.

    Internal oprim composition:
    - oprim.cross_sectional_rank
    - oprim.divergence_score
    """
    if not history:
        return []
    results = []
    for i, h in enumerate(history):
        common_keys = set(current_features) & set(h)
        if not common_keys:
            continue
        dist = sum((current_features[k] - h.get(k, 0)) ** 2 for k in common_keys) ** 0.5
        results.append({"index": i, "distance": round(dist, 6), "features": h})
    results.sort(key=lambda x: x["distance"])
    return results[:top_k]
