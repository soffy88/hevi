"""Tests for oskill.regime_conditional_score_weighted."""

import pytest

from oskill.regime_conditional_score_weighted import regime_conditional_score_weighted

BASE_WEIGHTS_8DIM = {
    "momentum": 0.15,
    "volume": 0.10,
    "sentiment": 0.10,
    "policy": 0.10,
    "technical": 0.10,
    "fundamentals": 0.15,
    "valuation": 0.15,
    "risk": 0.15,
}

REGIME_OVERRIDES = {
    "积极": {"momentum": 1.3, "volume": 1.2, "sentiment": 1.2, "valuation": 0.7},
    "狂热": {"risk": 1.8, "valuation": 1.3, "momentum": 0.7, "sentiment": 0.6},
    "谨慎": {},
}


class TestNoOverride:
    def test_uses_base_weights(self) -> None:
        dim_scores = {k: 70.0 for k in BASE_WEIGHTS_8DIM}
        result = regime_conditional_score_weighted(
            dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, "谨慎"
        )
        assert result.total_score == pytest.approx(70.0)
        for dim, w in result.weights_used.items():
            assert w == pytest.approx(BASE_WEIGHTS_8DIM[dim])
        assert all(not c.is_boosted and not c.is_dampened for c in result.dim_contributions)

    def test_unknown_regime_uses_base(self) -> None:
        dim_scores = {k: 70.0 for k in BASE_WEIGHTS_8DIM}
        result = regime_conditional_score_weighted(
            dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, "unknown_xxx"
        )
        assert result.total_score == pytest.approx(70.0)


class TestActiveRegime:
    def test_boosts_momentum_dampens_valuation(self) -> None:
        dim_scores = {
            "momentum": 92.0,
            "volume": 88.0,
            "sentiment": 85.0,
            "policy": 90.0,
            "technical": 75.0,
            "fundamentals": 68.0,
            "valuation": 55.0,
            "risk": 65.0,
        }
        result = regime_conditional_score_weighted(
            dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, "积极"
        )
        assert result.weights_used["momentum"] > BASE_WEIGHTS_8DIM["momentum"]
        assert result.weights_used["valuation"] < BASE_WEIGHTS_8DIM["valuation"]

        momentum_c = next(c for c in result.dim_contributions if c.dim_name == "momentum")
        assert momentum_c.is_boosted is True
        valuation_c = next(c for c in result.dim_contributions if c.dim_name == "valuation")
        assert valuation_c.is_dampened is True


class TestMathConsistency:
    def test_weights_sum_to_1(self) -> None:
        dim_scores = {k: 70.0 for k in BASE_WEIGHTS_8DIM}
        for regime in ["谨慎", "积极", "狂热"]:
            result = regime_conditional_score_weighted(
                dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, regime
            )
            assert sum(result.weights_used.values()) == pytest.approx(1.0)

    def test_total_equals_sum_contributions(self) -> None:
        dim_scores = {
            "momentum": 92.0,
            "volume": 88.0,
            "sentiment": 85.0,
            "policy": 90.0,
            "technical": 75.0,
            "fundamentals": 68.0,
            "valuation": 55.0,
            "risk": 65.0,
        }
        result = regime_conditional_score_weighted(
            dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, "积极"
        )
        assert result.total_score == pytest.approx(
            sum(c.contribution for c in result.dim_contributions)
        )

    def test_specific_hand_calculation(self) -> None:
        """Verify: 7 dims at 70, momentum at 100, regime=积极."""
        dim_scores = {
            "momentum": 100.0,
            "volume": 70.0,
            "sentiment": 70.0,
            "policy": 70.0,
            "technical": 70.0,
            "fundamentals": 70.0,
            "valuation": 70.0,
            "risk": 70.0,
        }
        result = regime_conditional_score_weighted(
            dim_scores, BASE_WEIGHTS_8DIM, REGIME_OVERRIDES, "积极"
        )
        # unnorm: momentum=0.195, volume=0.12, sentiment=0.12, valuation=0.105,
        # policy=0.10, technical=0.10, fundamentals=0.15, risk=0.15
        # sum = 1.04
        # total = 100*(0.195/1.04) + 70*(1 - 0.195/1.04) = 18.75 + 56.875 = 75.625
        assert result.total_score == pytest.approx(75.625, abs=0.01)


class TestInputValidation:
    def test_empty_scores_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            regime_conditional_score_weighted({}, {}, {}, "积极")

    def test_weights_not_summing_to_1_raises(self) -> None:
        with pytest.raises(ValueError, match="must sum to 1.0"):
            regime_conditional_score_weighted(
                {"a": 70.0, "b": 70.0}, {"a": 0.5, "b": 0.6}, {}, "谨慎"
            )

    def test_mismatched_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="same keys"):
            regime_conditional_score_weighted(
                {"momentum": 70.0}, {"momentum": 0.5, "volume": 0.5}, {}, "谨慎"
            )
