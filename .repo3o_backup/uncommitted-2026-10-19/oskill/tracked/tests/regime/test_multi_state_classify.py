"""Tests for oskill.regime.multi_state_classify."""

from __future__ import annotations

import pytest

from oskill.regime.multi_state_classify import multi_state_classify


def _hot_state_def():
    return {
        "name": "hot",
        "conditions": [{"field": "limit_up_count", "op": "gte", "value": 80}],
        "exclusive": True,
        "priority": 1,
    }


def _warm_state_def():
    return {
        "name": "warm",
        "conditions": [{"field": "limit_up_count", "op": "gte", "value": 40}],
        "exclusive": True,
        "priority": 2,
    }


def _cold_state_def():
    return {
        "name": "cold",
        "conditions": [{"field": "limit_up_count", "op": "lt", "value": 10}],
        "exclusive": True,
        "priority": 3,
    }


class TestMultiStateClassify:
    def test_hot_state_matched(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def(), _warm_state_def(), _cold_state_def()],
        )
        assert result["current_state"] == "hot"

    def test_unknown_state_when_no_match(self):
        result = multi_state_classify(
            {"limit_up_count": 20},
            [_hot_state_def(), _cold_state_def()],
        )
        assert result["current_state"] == "unknown"
        assert result["confidence"] == 0.0

    def test_confidence_set_when_matched(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def()],
        )
        assert 0.0 < result["confidence"] <= 1.0

    def test_matched_states_list_populated(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def(), _warm_state_def()],
        )
        assert "hot" in result["matched_states"]
        assert "warm" in result["matched_states"]

    def test_priority_selects_lowest_priority_number(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_warm_state_def(), _hot_state_def()],  # reversed order
        )
        # hot has priority=1, warm has priority=2; hot wins
        assert result["current_state"] == "hot"

    def test_transition_valid_true_by_default(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def()],
        )
        assert result["transition_valid"] is True

    def test_transition_valid_respected(self):
        # prev_state=cold, but only warm is allowed to transition to hot
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def()],
            transition_rules={"cold": {"warm"}},  # cold can only go to warm
            prev_state="cold",
        )
        assert result["transition_valid"] is False

    def test_transition_valid_allowed(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def()],
            transition_rules={"warm": {"hot"}},  # warm can go to hot
            prev_state="warm",
        )
        assert result["transition_valid"] is True

    def test_transition_no_prev_state_always_valid(self):
        result = multi_state_classify(
            {"limit_up_count": 90},
            [_hot_state_def()],
            transition_rules={"cold": {"warm"}},
            prev_state=None,
        )
        assert result["transition_valid"] is True

    def test_transition_rules_none_always_valid(self):
        result = multi_state_classify(
            {"limit_up_count": 5},
            [_cold_state_def()],
            transition_rules=None,
            prev_state="hot",
        )
        assert result["transition_valid"] is True

    def test_unknown_state_transition_always_valid(self):
        result = multi_state_classify(
            {"limit_up_count": 20},
            [_hot_state_def()],
            transition_rules={"warm": {"cold"}},
            prev_state="warm",
        )
        assert result["current_state"] == "unknown"
        assert result["transition_valid"] is True

    def test_empty_state_definitions_unknown(self):
        result = multi_state_classify({"limit_up_count": 90}, [])
        assert result["current_state"] == "unknown"

    @pytest.mark.academic_reference
    def test_hamilton1989_markov_regime_classification(self):
        """Hamilton (1989) Econometrica: regime classification with transition validation.

        Two regimes: expansion (GDP growth >= 2) and recession (GDP growth < 0).
        With transition_rules, recession can only move to expansion via recovery.
        Given expansion indicators, state=expansion; transition from recession is valid
        only when expansion is allowed.
        """
        state_defs = [
            {
                "name": "expansion",
                "conditions": [{"field": "gdp_growth", "op": "gte", "value": 2.0}],
                "exclusive": True,
                "priority": 1,
            },
            {
                "name": "recession",
                "conditions": [{"field": "gdp_growth", "op": "lt", "value": 0.0}],
                "exclusive": True,
                "priority": 2,
            },
        ]
        transition_rules = {
            "recession": {"expansion"},  # can exit recession -> expansion
            "expansion": {"expansion", "recession"},
        }
        result = multi_state_classify(
            {"gdp_growth": 3.5},
            state_defs,
            transition_rules=transition_rules,
            prev_state="recession",
        )
        assert result["current_state"] == "expansion"
        assert result["transition_valid"] is True
        assert result["confidence"] > 0.0


# --- Sprint 12 E1 extension tests ---


class TestE1NStatesConstraint:
    def test_backward_compat_6_states_unchanged(self) -> None:
        """Without n_states_constraint, n_states field is added to output."""
        from unittest.mock import patch

        states = [{"name": f"s{i}", "conditions": [], "priority": i} for i in range(6)]
        # Mock the classifier to return a simple result
        with patch("oskill.regime.multi_state_classify.rule_based_classifier") as mock_cls:
            mock_cls.return_value = {"matched_labels": ["s3"], "scores": {"s3": 0.8}}
            result = multi_state_classify({"x": 55}, states)
        assert "n_states" in result
        assert result["n_states"] == 6
        assert result["current_state"] == "s3"

    def test_7_states_fixture_tide_v3(self) -> None:
        """7-state emotion classification for Tide v3."""
        from unittest.mock import patch

        states = [
            {"name": "冰点", "conditions": [], "priority": 1},
            {"name": "恐慌", "conditions": [], "priority": 2},
            {"name": "分歧", "conditions": [], "priority": 3},
            {"name": "犹豫", "conditions": [], "priority": 4},
            {"name": "谨慎", "conditions": [], "priority": 5},
            {"name": "积极", "conditions": [], "priority": 6},
            {"name": "狂热", "conditions": [], "priority": 7},
        ]
        with patch("oskill.regime.multi_state_classify.rule_based_classifier") as mock_cls:
            mock_cls.return_value = {"matched_labels": ["分歧"], "scores": {"分歧": 0.9}}
            result = multi_state_classify({"score": 30}, states, n_states_constraint=7)
        assert result["n_states"] == 7
        assert result["current_state"] == "分歧"

    def test_n_states_constraint_mismatch_raises(self) -> None:
        """Mismatch between constraint and actual definitions raises."""
        states = [
            {"name": "a", "conditions": [], "priority": 1},
        ]
        with pytest.raises(ValueError, match="n_states_constraint=7"):
            multi_state_classify({"x": 5}, states, n_states_constraint=7)
