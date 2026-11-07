"""Tests for signal_fusion_skills oskills (12 new)."""

from oskill.signal_fusion_skills import (
    alphalens_style_ic,
    backtest_metric_suite,
    behavioral_weighting,
    counterfactual_generator,
    data_drift_detector,
    fusion_score_with_uncertainty,
    pack_evaluation,
    regime_aware_scoring,
    relative_strength_rank,
    signal_quality_gate,
    temporal_fusion,
    walkforward_validator,
)


def test_fusion_score_with_uncertainty():
    r = fusion_score_with_uncertainty(raw_signals={"trend": 0.8, "flow": 0.5})
    assert "fusion_score" in r
    assert "uncertainty" in r
    assert isinstance(r["abstain"], bool)


def test_fusion_score_empty():
    r = fusion_score_with_uncertainty(raw_signals={})
    assert r["abstain"] is True


def test_signal_quality_gate():
    r = signal_quality_gate(signals={"trend": 0.9, "noise": 0.1})
    assert "passed" in r and "gated" in r


def test_temporal_fusion():
    r = temporal_fusion(signals={"a": 0.8}, ages_hours={"a": 12}, tf1_signal=0.7, tf4_signal=0.6)
    assert r["decayed_signals"]["a"] < 0.8
    assert "consistency" in r


def test_behavioral_weighting():
    r = behavioral_weighting(
        signals={"trend": 0.8}, frequencies={"trend": 10}, total_signals=100, sentiment_score=0.9
    )
    assert "weighted" in r


def test_pack_evaluation():
    r = pack_evaluation(historical_packs=[{"score": 60}], new_pack={"score": 75})
    assert "promote" in r
    assert "posterior" in r


def test_alphalens_style_ic():
    r = alphalens_style_ic(ic_series=[0.1, 0.09, 0.05, 0.03], oos_start_idx=2)
    assert "ic_decay" in r
    assert "attribution" in r


def test_regime_aware_scoring():
    r = regime_aware_scoring(
        ic_series=[0.1, -0.05], regime_labels=["bull", "bear"], asset_scores={"BTC": 80}
    )
    assert "regime_ic" in r
    assert "ranks" in r


def test_relative_strength_rank():
    r = relative_strength_rank(asset_scores={"BTC": 80, "ETH": 60})
    assert r["ranks"]["BTC"] > r["ranks"]["ETH"]


def test_relative_strength_rank_with_corr():
    r = relative_strength_rank(
        asset_scores={"A": 80, "B": 60}, returns={"A": [1, 2, 3], "B": [1, 2, 3]}
    )
    assert r["correlation"] is not None


def test_backtest_metric_suite():
    r = backtest_metric_suite(equity_curve=[100, 105, 103, 110, 115])
    assert r["sharpe"] != 0
    assert r["max_drawdown"] > 0
    assert r["total_return"] > 0


def test_backtest_metric_suite_empty():
    r = backtest_metric_suite(equity_curve=[])
    assert r["sharpe"] == 0


def test_walkforward_validator():
    r = walkforward_validator(data=[100 + i for i in range(100)], window_size=30, step_size=10)
    assert len(r) > 0
    assert "sharpe" in r[0]


def test_data_drift_detector_no_drift():
    r = data_drift_detector(reference=[1, 2, 3, 4, 5] * 10, current=[1, 2, 3, 4, 5] * 10)
    assert r["drifted"] is False


def test_data_drift_detector_drift():
    r = data_drift_detector(reference=[1] * 50, current=[100] * 50)
    assert r["drifted"] is True


def test_counterfactual_generator():
    r = counterfactual_generator(
        base_scenario={"trend": 0.8, "flow": 0.5}, perturbations={"trend": -0.5}
    )
    assert len(r) == 1
    assert r[0]["scenario"] == "trend_shock"
