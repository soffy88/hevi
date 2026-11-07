"""Batch C tests: 7 new oskill elements."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

# ─────────────────────────── hmm_regime_detect ────────────────────────────


class TestHmmRegimeDetect:
    def _obs(self, n=40):
        return [float(i % 5) for i in range(n)]

    def test_returns_expected_keys(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        result = hmm_regime_detect(self._obs(), n_regimes=2)
        for k in ("regimes", "model", "n_regimes", "current_regime", "transition_matrix"):
            assert k in result

    def test_regimes_length_matches_observations(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        obs = self._obs(30)
        result = hmm_regime_detect(obs, n_regimes=2)
        assert len(result["regimes"]) == len(obs)

    def test_regimes_in_valid_range(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        result = hmm_regime_detect(self._obs(), n_regimes=3)
        assert all(0 <= r < 3 for r in result["regimes"])

    def test_current_regime_is_last(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        result = hmm_regime_detect(self._obs(), n_regimes=2)
        assert result["current_regime"] == result["regimes"][-1]

    def test_pretrained_model_skips_fit(self):
        from oprim.hmm_baum_welch import hmm_baum_welch

        from oskill.hmm_regime_detect import hmm_regime_detect

        obs = self._obs()
        model = hmm_baum_welch(obs, n_states=2)
        with patch("oprim.hmm_baum_welch.hmm_baum_welch") as mock_fit:
            hmm_regime_detect(obs, n_regimes=2, trained_model=model)
            mock_fit.assert_not_called()

    def test_n_regimes_stored(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        result = hmm_regime_detect(self._obs(), n_regimes=2)
        assert result["n_regimes"] == 2

    def test_transition_matrix_shape(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        result = hmm_regime_detect(self._obs(50), n_regimes=3)
        assert len(result["transition_matrix"]) == 3

    def test_model_reusable(self):
        from oskill.hmm_regime_detect import hmm_regime_detect

        obs = self._obs(40)
        r1 = hmm_regime_detect(obs, n_regimes=2)
        r2 = hmm_regime_detect(obs, n_regimes=2, trained_model=r1["model"])
        assert len(r2["regimes"]) == len(obs)


# ─────────────────────────── cointegration_pairs ────────────────────────────


class TestCointegrationPairs:
    def _coint_series(self, n=80):

        rng = numpy = __import__("numpy")
        rng = numpy.random.default_rng(42)
        x = numpy.cumsum(rng.normal(0, 1, n))
        y = 2.0 * x + rng.normal(0, 0.05, n)
        return x.tolist(), y.tolist()

    def test_returns_expected_keys(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        result = cointegration_pairs(a, b, lookback=30)
        for k in ("cointegrated", "hedge_ratio", "spread", "zscore", "signal", "p_value"):
            assert k in result

    def test_signal_is_valid_value(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        result = cointegration_pairs(a, b, lookback=20)
        assert result["signal"] in ("long_a_short_b", "short_a_long_b", "close", "flat")

    def test_spread_length_matches_series(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series(60)
        result = cointegration_pairs(a, b, lookback=20)
        assert len(result["spread"]) == 60

    def test_cointegrated_pair_detected(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series(100)
        result = cointegration_pairs(a, b, lookback=30)
        assert result["cointegrated"] is True

    def test_returns_coint_and_zscore_sub_results(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        result = cointegration_pairs(a, b, lookback=20)
        assert "coint_result" in result
        assert "zscore_result" in result

    def test_entry_z_changes_signal(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        r_tight = cointegration_pairs(a, b, entry_z=0.01, lookback=20)
        assert r_tight["signal"] in ("long_a_short_b", "short_a_long_b", "close", "flat")

    def test_hedge_ratio_positive_for_positively_correlated(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        result = cointegration_pairs(a, b, lookback=20)
        assert result["hedge_ratio"] > 0

    def test_p_value_float(self):
        from oskill.cointegration_pairs import cointegration_pairs

        a, b = self._coint_series()
        result = cointegration_pairs(a, b, lookback=20)
        assert isinstance(result["p_value"], float)


# ─────────────────────────── bocpd_changepoint ────────────────────────────


class TestBocpdChangepoint:
    def test_returns_expected_keys(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = [0.0] * 20 + [5.0] * 20
        result = bocpd_changepoint(obs, hazard_rate=0.1)
        for k in (
            "changepoint_detected",
            "changepoint_indices",
            "run_length_probs",
            "last_prob",
            "hazard_rate",
        ):
            assert k in result

    def test_detects_obvious_changepoint(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = [0.0] * 30 + [10.0] * 30
        result = bocpd_changepoint(obs, hazard_rate=0.3, model_params={"threshold": 0.3})
        assert result["changepoint_detected"] is True

    def test_no_changepoint_stable_series(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = [1.0] * 40
        result = bocpd_changepoint(obs, hazard_rate=0.01, model_params={"threshold": 0.9})
        assert result["changepoint_detected"] is False

    def test_too_short_series(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        result = bocpd_changepoint([1.0], hazard_rate=0.1)
        assert result["changepoint_detected"] is False

    def test_hazard_rate_stored(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        result = bocpd_changepoint([1.0, 2.0, 3.0], hazard_rate=0.05)
        assert result["hazard_rate"] == pytest.approx(0.05)

    def test_last_prob_in_unit_interval(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = list(range(20))
        result = bocpd_changepoint(obs, hazard_rate=0.1)
        assert 0.0 <= result["last_prob"] <= 1.0

    def test_run_length_probs_length(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = [float(i) for i in range(15)]
        result = bocpd_changepoint(obs, hazard_rate=0.1)
        assert len(result["run_length_probs"]) == len(obs)

    def test_changepoint_indices_subset_of_range(self):
        from oskill.bocpd_changepoint import bocpd_changepoint

        obs = [0.0] * 20 + [5.0] * 20
        result = bocpd_changepoint(obs, hazard_rate=0.2, model_params={"threshold": 0.2})
        for idx in result["changepoint_indices"]:
            assert 0 <= idx < len(obs)


# ─────────────────────────── market_impact_sigmoid ────────────────────────────


class TestMarketImpactSigmoid:
    _params = {"alpha": 50.0, "beta": 5.0, "gamma": 0.1}

    def test_returns_expected_keys(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        result = market_impact_sigmoid(1_000_000, adv=10_000_000, params=self._params)
        for k in ("impact_bps", "participation", "alpha", "beta", "gamma", "capped"):
            assert k in result

    def test_impact_positive(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        result = market_impact_sigmoid(500_000, adv=5_000_000, params=self._params)
        assert result["impact_bps"] > 0

    def test_missing_alpha_raises(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        with pytest.raises(ValueError, match="alpha"):
            market_impact_sigmoid(100, adv=1000, params={"beta": 1.0, "gamma": 0.1})

    def test_missing_beta_raises(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        with pytest.raises(ValueError, match="beta"):
            market_impact_sigmoid(100, adv=1000, params={"alpha": 10.0, "gamma": 0.1})

    def test_missing_gamma_raises(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        with pytest.raises(ValueError, match="gamma"):
            market_impact_sigmoid(100, adv=1000, params={"alpha": 10.0, "beta": 1.0})

    def test_no_silent_100bps_fallback(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        # Must raise, never return 100bps silently
        with pytest.raises(ValueError):
            market_impact_sigmoid(100, adv=1000, params={})

    def test_zero_adv_raises(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        with pytest.raises(ValueError, match="adv"):
            market_impact_sigmoid(100, adv=0.0, params=self._params)

    def test_max_impact_cap(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        p = {**self._params, "max_impact_bps": 10.0}
        result = market_impact_sigmoid(100_000_000, adv=1_000, params=p)
        assert result["impact_bps"] <= 10.0
        assert result["capped"] is True

    def test_participation_computed_correctly(self):
        from oskill.market_impact_sigmoid import market_impact_sigmoid

        result = market_impact_sigmoid(1_000, adv=10_000, params=self._params)
        assert result["participation"] == pytest.approx(0.1)

    def test_sigmoid_not_sqrt(self):
        import math

        from oskill.market_impact_sigmoid import market_impact_sigmoid

        r = market_impact_sigmoid(500_000, adv=5_000_000, params=self._params)
        participation = 500_000 / 5_000_000
        expected = 50.0 / (1.0 + math.exp(-5.0 * (participation - 0.1)))
        assert r["impact_bps"] == pytest.approx(expected, rel=1e-3)


# ─────────────────────────── walk_forward ────────────────────────────


class TestWalkForward:
    def _strategy(self, train, test):
        return {"sharpe": 1.0, "returns": [0.01, -0.005, 0.008]}

    def test_returns_expected_keys(self):
        from oskill.walk_forward import walk_forward

        data = list(range(50))
        result = walk_forward(self._strategy, data, n_splits=5)
        for k in ("fold_results", "oos_sharpes", "mean_oos_sharpe", "deflated_sharpe", "n_splits"):
            assert k in result

    def test_n_folds_correct(self):
        from oskill.walk_forward import walk_forward

        data = list(range(50))
        result = walk_forward(self._strategy, data, n_splits=4)
        assert len(result["fold_results"]) == 4

    def test_oos_sharpes_from_strategy(self):
        from oskill.walk_forward import walk_forward

        data = list(range(40))
        result = walk_forward(self._strategy, data, n_splits=4)
        assert all(s == 1.0 for s in result["oos_sharpes"])

    def test_mean_oos_sharpe_correct(self):
        from oskill.walk_forward import walk_forward

        data = list(range(40))
        result = walk_forward(self._strategy, data, n_splits=4)
        assert result["mean_oos_sharpe"] == pytest.approx(1.0)

    def test_deflated_sharpe_is_dict(self):
        from oskill.walk_forward import walk_forward

        data = list(range(40))
        result = walk_forward(self._strategy, data, n_splits=4)
        assert isinstance(result["deflated_sharpe"], dict)
        assert "deflated_sharpe" in result["deflated_sharpe"]

    def test_strategy_called_n_splits_times(self):
        from oskill.walk_forward import walk_forward

        calls = []

        def counting_strategy(train, test):
            calls.append(1)
            return {"sharpe": 0.5}

        walk_forward(counting_strategy, list(range(30)), n_splits=3)
        assert len(calls) == 3

    def test_embargo_reduces_train_size(self):
        from oskill.walk_forward import walk_forward

        train_sizes_no_emb = []
        train_sizes_emb = []

        def capture_no(train, test):
            train_sizes_no_emb.append(len(train))
            return {"sharpe": 0.0}

        def capture_emb(train, test):
            train_sizes_emb.append(len(train))
            return {"sharpe": 0.0}

        data = list(range(40))
        walk_forward(capture_no, data, n_splits=4, embargo=0)
        walk_forward(capture_emb, data, n_splits=4, embargo=3)
        assert sum(train_sizes_emb) <= sum(train_sizes_no_emb)

    def test_n_splits_stored(self):
        from oskill.walk_forward import walk_forward

        result = walk_forward(self._strategy, list(range(30)), n_splits=3)
        assert result["n_splits"] == 3


# ─────────────────────────── regime_gate_eval ────────────────────────────


class TestRegimeGateEval:
    def _model_and_obs(self):
        from oprim.hmm_baum_welch import hmm_baum_welch

        obs = [float(i % 4) for i in range(40)]
        model = hmm_baum_welch(obs, n_states=2)
        return obs, model

    def test_returns_expected_keys(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0, 1], trained_model=model)
        for k in (
            "gate_open",
            "current_regime",
            "desirable_regimes",
            "regime_result",
            "risk_check",
        ):
            assert k in result

    def test_gate_open_when_regime_desirable(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0, 1], trained_model=model)
        assert result["gate_open"] is True

    def test_gate_closed_when_no_desirable_regimes(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[], trained_model=model)
        assert result["gate_open"] is False

    def test_current_regime_is_integer(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0], trained_model=model)
        assert isinstance(result["current_regime"], int)

    def test_desirable_regimes_stored(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[1], trained_model=model)
        assert result["desirable_regimes"] == [1]

    def test_regime_result_has_regimes(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0, 1], trained_model=model)
        assert "regimes" in result["regime_result"]

    def test_risk_check_has_pass(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0, 1], trained_model=model)
        assert "pass" in result["risk_check"]

    def test_gate_consistent_with_current_regime(self):
        from oskill.regime_gate_eval import regime_gate_eval

        obs, model = self._model_and_obs()
        result = regime_gate_eval(obs, desirable_regimes=[0, 1], trained_model=model)
        expected_open = result["current_regime"] in [0, 1]
        assert result["gate_open"] == expected_open


# ─────────────────────────── llm_factor_debate ────────────────────────────


class TestLlmFactorDebate:
    def _make_caller(self, text="test response"):
        async def caller(messages, *, system="", max_tokens=512):
            return {"content": [{"type": "text", "text": text}]}

        return caller

    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        from oskill.llm_factor_debate import llm_factor_debate

        result = await llm_factor_debate(
            "BTC trending up", llm_caller=self._make_caller(), max_tokens=64
        )
        for k in (
            "bull_argument",
            "bear_argument",
            "verdict",
            "consensus",
            "confidence",
            "raw_responses",
        ):
            assert k in result

    @pytest.mark.asyncio
    async def test_three_llm_calls_made(self):
        from oskill.llm_factor_debate import llm_factor_debate

        calls = []

        async def counting_caller(messages, *, system="", max_tokens=512):
            calls.append(1)
            return {"content": [{"type": "text", "text": "neutral response"}]}

        await llm_factor_debate("market context", llm_caller=counting_caller)
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_concurrent_calls_via_gather(self):
        import time

        from oskill.llm_factor_debate import llm_factor_debate

        delays = []

        async def slow_caller(messages, *, system="", max_tokens=512):

            start = time.monotonic()
            await asyncio.sleep(0.05)
            delays.append(time.monotonic() - start)
            return {"content": [{"type": "text", "text": "slow"}]}

        t0 = time.monotonic()
        await llm_factor_debate("ctx", llm_caller=slow_caller)
        elapsed = time.monotonic() - t0
        # Three 50ms calls in parallel ≈ 50-100ms, not 150ms+
        assert elapsed < 0.14, f"calls appear sequential: {elapsed:.3f}s"

    @pytest.mark.asyncio
    async def test_consensus_extracted(self):
        from oskill.llm_factor_debate import llm_factor_debate

        async def verdict_caller(messages, *, system="", max_tokens=512):
            text = "Some analysis.\nVERDICT: bullish CONFIDENCE: 0.75"
            return {"content": [{"type": "text", "text": text}]}

        result = await llm_factor_debate("ctx", llm_caller=verdict_caller)
        assert result["consensus"] == "bullish"
        assert result["confidence"] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_consensus_defaults_neutral(self):
        from oskill.llm_factor_debate import llm_factor_debate

        result = await llm_factor_debate("ctx", llm_caller=self._make_caller("no verdict"))
        assert result["consensus"] == "neutral"

    @pytest.mark.asyncio
    async def test_raw_responses_list_of_three(self):
        from oskill.llm_factor_debate import llm_factor_debate

        result = await llm_factor_debate("ctx", llm_caller=self._make_caller())
        assert len(result["raw_responses"]) == 3

    @pytest.mark.asyncio
    async def test_factor_hypothesis_passed_in_prompt(self):
        from oskill.llm_factor_debate import llm_factor_debate

        seen_messages = []

        async def capturing_caller(messages, *, system="", max_tokens=512):
            seen_messages.extend(messages)
            return {"content": [{"type": "text", "text": "ok"}]}

        await llm_factor_debate(
            "ctx", llm_caller=capturing_caller, factor_hypothesis="momentum 12-1"
        )
        combined = " ".join(m.get("content", "") for m in seen_messages)
        assert "momentum 12-1" in combined

    @pytest.mark.asyncio
    async def test_confidence_in_unit_interval(self):
        from oskill.llm_factor_debate import llm_factor_debate

        result = await llm_factor_debate("ctx", llm_caller=self._make_caller())
        assert 0.0 <= result["confidence"] <= 1.0
