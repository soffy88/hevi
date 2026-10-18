"""Signal fusion oskills — composite analysis combining multiple oprims."""

from __future__ import annotations


class SignalFusionSkillError(Exception):
    """Raised when a signal fusion skill fails."""


def fusion_score_with_uncertainty(
    *,
    raw_signals: dict[str, float],
    prior: dict | None = None,
    abstain_threshold: float = 0.7,
) -> dict:
    """Compute fusion score with Bayesian uncertainty and abstain logic.

    Internal oprim composition:
    - oprim.bayesian_factor_posterior
    - oprim.divergence_score
    - oprim.abstain_decision

    Example:
        >>> fusion_score_with_uncertainty(raw_signals={"trend": 0.8, "flow": 0.5})
        {'fusion_score': 0.65, 'uncertainty': 0.2, 'abstain': False, ...}
    """
    from oprim import abstain_decision, bayesian_factor_posterior

    values = list(raw_signals.values())
    if not values:
        return {
            "fusion_score": 0,
            "uncertainty": 1.0,
            "abstain": True,
            "confidence_interval": (0, 0),
        }
    mean_signal = sum(values) / len(values)
    std_signal = (sum((v - mean_signal) ** 2 for v in values) / max(len(values) - 1, 1)) ** 0.5
    p = prior or {"mean": 0, "std": 1}
    posterior = bayesian_factor_posterior(
        prior=p, likelihood={"mean": mean_signal, "std": max(std_signal, 0.01)}
    )
    uncertainty = std_signal / max(abs(mean_signal), 0.01)
    confidence = 1.0 - min(1.0, uncertainty)
    decision = abstain_decision(
        confidence=confidence, uncertainty=min(1.0, uncertainty), threshold=abstain_threshold
    )
    return {
        "fusion_score": round(posterior["posterior_mean"] * 100, 2),
        "uncertainty": round(min(1.0, uncertainty), 4),
        "abstain": decision == "abstain",
        "confidence_interval": (posterior["ci_low"], posterior["ci_high"]),
    }


def signal_quality_gate(
    *,
    signals: dict[str, float],
    frequencies: dict[str, int] | None = None,
    total_signals: int = 100,
    confidence_threshold: float = 0.7,
) -> dict:
    """Gate signals by quality (rarity + confidence + rank).

    Internal oprim composition:
    - oprim.abstain_decision
    - oprim.signal_rarity_weight
    - oprim.cross_sectional_rank

    Example:
        >>> signal_quality_gate(signals={"trend": 0.8, "flow": 0.3})
        {'passed': ['trend'], 'gated': ['flow'], ...}
    """
    from oprim import abstain_decision, cross_sectional_rank, signal_rarity_weight

    ranks = cross_sectional_rank(asset_scores=signals, method="percentile")
    passed, gated = [], []
    for name, score in signals.items():
        freq = (frequencies or {}).get(name, total_signals // 2)
        weight = signal_rarity_weight(
            signal_frequency=max(1, freq), total_signals=max(1, total_signals)
        )
        confidence = min(1.0, abs(score) * weight / 3)
        decision = abstain_decision(
            confidence=confidence, uncertainty=1 - confidence, threshold=confidence_threshold
        )
        if decision == "proceed":
            passed.append(name)
        else:
            gated.append(name)
    return {"passed": passed, "gated": gated, "ranks": ranks}


def temporal_fusion(
    *,
    signals: dict[str, float],
    ages_hours: dict[str, float],
    tf1_signal: float = 0.0,
    tf4_signal: float = 0.0,
    half_life: float = 24.0,
) -> dict:
    """Fuse signals with temporal decay and cross-timeframe consistency.

    Internal oprim composition:
    - oprim.signal_temporal_decay
    - oprim.cross_timeframe_consistency

    Example:
        >>> temporal_fusion(signals={"a": 0.8}, ages_hours={"a": 12}, tf1_signal=0.7)
        {'decayed_signals': {...}, 'consistency': 0.66, ...}
    """
    from oprim import cross_timeframe_consistency, signal_temporal_decay

    decayed = {}
    for name, val in signals.items():
        age = ages_hours.get(name, 0)
        decayed[name] = round(
            signal_temporal_decay(signal=val, age_hours=age, half_life=half_life), 6
        )
    consistency = cross_timeframe_consistency(tf1_signal=tf1_signal, tf4_signal=tf4_signal)
    return {
        "decayed_signals": decayed,
        "consistency": consistency,
        "tf_aligned": abs(consistency) > 0.3,
    }


def behavioral_weighting(
    *,
    signals: dict[str, float],
    frequencies: dict[str, int],
    total_signals: int,
    sentiment_score: float = 0.0,
) -> dict:
    """Weight signals by rarity and trend-sentiment synergy.

    Internal oprim composition:
    - oprim.signal_rarity_weight
    - oprim.trend_sentiment_synergy

    Example:
        >>> behavioral_weighting(signals={"trend": 0.8}, frequencies={"trend": 10},
        ...                    total_signals=100, sentiment_score=0.9)
        {'weighted': {'trend': ...}, ...}
    """
    from oprim import signal_rarity_weight, trend_sentiment_synergy

    weighted = {}
    for name, val in signals.items():
        freq = frequencies.get(name, total_signals // 2)
        rarity = signal_rarity_weight(
            signal_frequency=max(1, freq), total_signals=max(1, total_signals)
        )
        synergy = trend_sentiment_synergy(trend_signal=val, sentiment_score=sentiment_score)
        weighted[name] = round(synergy * min(rarity, 5.0) / 5.0, 6)
    return {"weighted": weighted, "sentiment_impact": sentiment_score}


def pack_evaluation(
    *,
    historical_packs: list[dict],
    new_pack: dict,
    prior: dict | None = None,
) -> dict:
    """Evaluate a new weight pack against historical performance.

    Internal oprim composition:
    - oprim.pack_promotion_test
    - oprim.bayesian_factor_posterior

    Example:
        >>> pack_evaluation(historical_packs=[{"score": 60}], new_pack={"score": 75})
        {'promote': True, 'posterior': {...}, ...}
    """
    from oprim import bayesian_factor_posterior, pack_promotion_test

    test = pack_promotion_test(historical_packs=historical_packs, new_pack=new_pack)
    hist_scores = [p.get("score", 0) for p in historical_packs] if historical_packs else [0]
    p = prior or {"mean": sum(hist_scores) / len(hist_scores), "std": 10}
    posterior = bayesian_factor_posterior(
        prior=p, likelihood={"mean": new_pack.get("score", 0), "std": 5}
    )
    return {
        "promote": test["promote"],
        "p_value": test["p_value"],
        "improvement": test["improvement"],
        "posterior": posterior,
    }


def alphalens_style_ic(
    *,
    ic_series: list[float],
    oos_start_idx: int,
    factor_contributions: dict[str, float] | None = None,
) -> dict:
    """Alphalens-style IC analysis with OOS decay and attribution.

    Internal oprim composition:
    - oprim.ic_oos_decay
    - oprim.factor_attribution

    Example:
        >>> alphalens_style_ic(ic_series=[0.1, 0.09, 0.05], oos_start_idx=1)
        {'ic_decay': {...}, 'attribution': {...}}
    """
    from oprim import factor_attribution, ic_oos_decay

    decay = ic_oos_decay(ic_series=ic_series, oos_start_idx=oos_start_idx)
    attr = factor_attribution(
        fusion_score=decay["ic_mean"] * 100,
        factor_contributions=factor_contributions or {"signal": decay["ic_mean"] * 100},
    )
    return {"ic_decay": decay, "attribution": attr}


def regime_aware_scoring(
    *,
    ic_series: list[float],
    regime_labels: list[str],
    asset_scores: dict[str, float],
) -> dict:
    """Score signals with regime conditioning and cross-sectional ranking.

    Internal oprim composition:
    - oprim.regime_conditional_ic
    - oprim.cross_sectional_rank

    Example:
        >>> regime_aware_scoring(ic_series=[0.1, -0.05], regime_labels=["bull", "bear"],
        ...                     asset_scores={"BTC": 80})
        {'regime_ic': {...}, 'ranks': {...}}
    """
    from oprim import cross_sectional_rank, regime_conditional_ic

    regime_ic = regime_conditional_ic(ic_series=ic_series, regime_labels=regime_labels)
    ranks = cross_sectional_rank(asset_scores=asset_scores)
    return {"regime_ic": regime_ic, "ranks": ranks}


def relative_strength_rank(
    *,
    asset_scores: dict[str, float],
    returns: dict[str, list[float]] | None = None,
) -> dict:
    """Rank assets by relative strength with optional correlation filter.

    Internal oprim composition:
    - oprim.cross_sectional_rank
    - oprim.correlation_matrix

    Example:
        >>> relative_strength_rank(asset_scores={"BTC": 80, "ETH": 60})
        {'ranks': {'BTC': 1.0, 'ETH': 0.0}, ...}
    """
    from oprim import correlation_matrix, cross_sectional_rank

    ranks = cross_sectional_rank(asset_scores=asset_scores)
    corr = None
    if returns and len(returns) > 1:
        corr = correlation_matrix(returns=returns)
    return {"ranks": ranks, "correlation": corr}


def backtest_metric_suite(
    *,
    equity_curve: list[float],
    trades: list[dict] | None = None,
) -> dict:
    """Compute comprehensive backtest metrics from equity curve.

    Internal oprim composition:
    - oprim.sharpe_ratio (existing)
    - oprim.drawdown_curve (existing)

    Example:
        >>> backtest_metric_suite(equity_curve=[100, 105, 103, 110])
        {'sharpe': ..., 'max_drawdown': ..., 'total_return': ...}
    """
    if not equity_curve or len(equity_curve) < 2:
        return {"sharpe": 0, "max_drawdown": 0, "total_return": 0, "trade_count": 0}
    returns = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]
    mean_r = sum(returns) / len(returns)
    std_r = (sum((r - mean_r) ** 2 for r in returns) / max(len(returns) - 1, 1)) ** 0.5
    sharpe = (mean_r / std_r * (252**0.5)) if std_r > 0 else 0
    peak = equity_curve[0]
    max_dd = 0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)
    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0]
    return {
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
        "total_return": round(total_return, 4),
        "trade_count": len(trades) if trades else 0,
    }


def walkforward_validator(
    *,
    data: list[float],
    window_size: int = 60,
    step_size: int = 20,
) -> list[dict]:
    """Walk-forward validation with rolling windows.

    Internal oprim composition:
    - oprim.rolling_window_split (existing)
    - oprim.sharpe_ratio (existing)

    Example:
        >>> walkforward_validator(data=[100+i for i in range(100)], window_size=30, step_size=10)
        [{'window': 0, 'sharpe': ...}, ...]
    """
    results = []
    i = 0
    window_idx = 0
    while i + window_size <= len(data):
        window = data[i : i + window_size]
        returns = [(window[j] - window[j - 1]) / window[j - 1] for j in range(1, len(window))]
        mean_r = sum(returns) / len(returns) if returns else 0
        std_r = (
            (sum((r - mean_r) ** 2 for r in returns) / max(len(returns) - 1, 1)) ** 0.5
            if returns
            else 0
        )
        sharpe = (mean_r / std_r * (252**0.5)) if std_r > 0 else 0
        results.append({"window": window_idx, "sharpe": round(sharpe, 4), "start_idx": i})
        i += step_size
        window_idx += 1
    return results


def data_drift_detector(
    *,
    reference: list[float],
    current: list[float],
    threshold: float = 0.1,
) -> dict:
    """Detect data distribution drift between reference and current windows.

    Internal oprim composition:
    - oprim.divergence_score
    - oprim.signal_failure_audit (for lineage)

    Example:
        >>> data_drift_detector(reference=[1,2,3,4,5], current=[5,6,7,8,9])
        {'drifted': True, 'divergence': ..., ...}
    """
    from oprim import divergence_score

    div = divergence_score(signal_a=reference, signal_b=current, method="js")
    return {"drifted": div > threshold, "divergence": round(div, 6), "threshold": threshold}


def counterfactual_generator(
    *,
    base_scenario: dict[str, float],
    perturbations: dict[str, float],
) -> list[dict]:
    """Generate counterfactual scenarios by perturbing base inputs.

    Internal oprim composition:
    - oprim.regime_conditional_ic
    - oprim.cross_sectional_rank

    Example:
        >>> counterfactual_generator(base_scenario={"trend": 0.8}, perturbations={"trend": -0.5})
        [{'scenario': 'trend_shock', 'values': {'trend': 0.3}, ...}]
    """
    from oprim import cross_sectional_rank

    scenarios = []
    for factor, delta in perturbations.items():
        perturbed = {**base_scenario}
        perturbed[factor] = base_scenario.get(factor, 0) + delta
        ranks = cross_sectional_rank(asset_scores=perturbed)
        scenarios.append(
            {"scenario": f"{factor}_shock", "values": perturbed, "ranks": ranks, "delta": delta}
        )
    return scenarios
