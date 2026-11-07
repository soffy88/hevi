"""Tests for backtest_strategy_skills oskills."""

from oskill.backtest_strategy_skills import *  # noqa: F403, F405
from oskill.backtest_strategy_skills import (
    comparative_score_anchoring,
    monte_carlo_significance_test,
    out_of_sample_validation,
    portfolio_backtest_simulation,
    risk_metrics_bundle,
    risk_scale_calculation,
    signal_crowding_analysis,
    similar_historical_context_search,
    strategy_benchmark_comparison,
    strategy_capacity_estimation,
    transaction_cost_model,
    turnover_churn_analysis,
    walk_forward_analysis,
)


def test_portfolio_backtest():
    r = portfolio_backtest_simulation(trades=[{"entry": 100, "exit": 110, "size": 1}])
    assert r["total_return"] > 0


def test_transaction_cost_model():
    r = transaction_cost_model(order_size=1000, avg_daily_volume=100000, volatility=0.02)
    assert r["total_cost"] > 0


def test_walk_forward():
    r = walk_forward_analysis(data=list(range(100)))
    assert r["train_size"] > 0


def test_monte_carlo_significance():
    r = monte_carlo_significance_test(strategy_returns=[0.01] * 50)
    assert "p_value" in r


def test_benchmark_comparison():
    r = strategy_benchmark_comparison(
        strategy_returns=[0.01, 0.02], benchmark_returns=[0.005, 0.01]
    )
    assert "alpha" in r


def test_capacity_estimation():
    r = strategy_capacity_estimation(avg_daily_volume=100000)
    assert r["estimated_capacity_usd"] > 0


def test_oos_validation():
    r = out_of_sample_validation(in_sample_sharpe=2.0, oos_sharpe=1.0)
    assert r["degradation"] == 0.5


def test_risk_metrics():
    r = risk_metrics_bundle(equity_curve=[100, 110, 105, 115, 120])
    assert r["max_dd"] > 0


def test_turnover_churn():
    r = turnover_churn_analysis(position_history=[{"A": 0.5}, {"A": 0.7}])
    assert r["avg_churn"] > 0


def test_crowding():
    r = signal_crowding_analysis(signal_counts={"buy": 80, "sell": 20}, total_participants=100)
    assert r["crowded"] is True


def test_comparative_anchoring():
    r = comparative_score_anchoring(current_score=90, historical_scores=[50, 60, 70, 80])
    assert r["percentile"] == 1.0


def test_risk_scale():
    r = risk_scale_calculation(
        positions={"BTC": 0.6}, factor_loadings={"BTC": {"market": 1.2}}, volatilities={"BTC": 0.03}
    )
    assert r["total_risk"] > 0


def test_similar_context():
    r = similar_historical_context_search(current_features={"a": 1}, history=[{"a": 1.1}, {"a": 5}])
    assert r[0]["distance"] < r[1]["distance"]
