"""Tests for oskill.classifier.rule_based."""

from __future__ import annotations

import pytest

from oskill.classifier.rule_based import rule_based_classifier, rule_based_veto_check


class TestRuleBasedClassifier:
    def test_empty_rule_table_no_matches(self):
        result = rule_based_classifier({"x": 1.0}, [])
        assert result["matched_labels"] == []
        assert result["exclusive_winner"] is None

    def test_single_rule_matches(self):
        rules = [{"label": "hot", "conditions": [{"field": "val", "op": "gte", "value": 80}]}]
        result = rule_based_classifier({"val": 90.0}, rules)
        assert "hot" in result["matched_labels"]

    def test_single_rule_no_match(self):
        rules = [{"label": "hot", "conditions": [{"field": "val", "op": "gte", "value": 80}]}]
        result = rule_based_classifier({"val": 70.0}, rules)
        assert result["matched_labels"] == []

    def test_multiple_conditions_all_must_match(self):
        rules = [
            {
                "label": "strong_buy",
                "conditions": [
                    {"field": "rsi", "op": "lte", "value": 30},
                    {"field": "volume_ratio", "op": "gte", "value": 2.0},
                ],
            }
        ]
        result = rule_based_classifier({"rsi": 25.0, "volume_ratio": 3.0}, rules)
        assert "strong_buy" in result["matched_labels"]

    def test_multiple_conditions_one_fails(self):
        rules = [
            {
                "label": "strong_buy",
                "conditions": [
                    {"field": "rsi", "op": "lte", "value": 30},
                    {"field": "volume_ratio", "op": "gte", "value": 2.0},
                ],
            }
        ]
        result = rule_based_classifier({"rsi": 25.0, "volume_ratio": 1.0}, rules)
        assert result["matched_labels"] == []

    def test_exclusive_winner_first_matching_exclusive(self):
        rules = [
            {
                "label": "A",
                "conditions": [{"field": "x", "op": "gte", "value": 5}],
                "exclusive": True,
            },
            {
                "label": "B",
                "conditions": [{"field": "x", "op": "gte", "value": 3}],
                "exclusive": True,
            },
        ]
        result = rule_based_classifier({"x": 6.0}, rules)
        assert result["exclusive_winner"] == "A"

    def test_exclusive_winner_none_if_no_exclusive(self):
        rules = [
            {"label": "A", "conditions": [{"field": "x", "op": "gte", "value": 5}]},
        ]
        result = rule_based_classifier({"x": 6.0}, rules)
        assert result["exclusive_winner"] is None

    def test_multiple_labels_all_matched(self):
        rules = [
            {"label": "A", "conditions": [{"field": "x", "op": "gt", "value": 0}]},
            {"label": "B", "conditions": [{"field": "x", "op": "lt", "value": 10}]},
        ]
        result = rule_based_classifier({"x": 5.0}, rules)
        assert "A" in result["matched_labels"]
        assert "B" in result["matched_labels"]

    def test_missing_field_no_match(self):
        rules = [{"label": "X", "conditions": [{"field": "missing", "op": "eq", "value": 1}]}]
        result = rule_based_classifier({"x": 1.0}, rules)
        assert result["matched_labels"] == []

    def test_score_is_1_for_single_condition(self):
        rules = [{"label": "A", "conditions": [{"field": "x", "op": "eq", "value": 5}]}]
        result = rule_based_classifier({"x": 5.0}, rules)
        assert result["scores"]["A"] == pytest.approx(1.0)

    def test_bool_feature_eq(self):
        rules = [{"label": "ST", "conditions": [{"field": "is_st", "op": "eq", "value": True}]}]
        result = rule_based_classifier({"is_st": True}, rules)
        assert "ST" in result["matched_labels"]

    def test_bool_feature_ne(self):
        rules = [{"label": "ST", "conditions": [{"field": "is_st", "op": "ne", "value": False}]}]
        result = rule_based_classifier({"is_st": True}, rules)
        assert "ST" in result["matched_labels"]

    def test_str_feature_eq(self):
        rules = [
            {
                "label": "TECH",
                "conditions": [{"field": "sector", "op": "eq", "value": "technology"}],
            }
        ]
        result = rule_based_classifier({"sector": "technology"}, rules)
        assert "TECH" in result["matched_labels"]

    def test_empty_conditions_rule_skipped(self):
        rules = [{"label": "A", "conditions": []}]
        result = rule_based_classifier({"x": 1.0}, rules)
        assert result["matched_labels"] == []

    def test_op_lte(self):
        rules = [{"label": "oversold", "conditions": [{"field": "rsi", "op": "lte", "value": 30}]}]
        result = rule_based_classifier({"rsi": 30.0}, rules)
        assert "oversold" in result["matched_labels"]

    def test_op_eq_numeric(self):
        rules = [{"label": "exact", "conditions": [{"field": "x", "op": "eq", "value": 42.0}]}]
        result = rule_based_classifier({"x": 42.0}, rules)
        assert "exact" in result["matched_labels"]

    def test_op_ne_numeric(self):
        rules = [{"label": "neq", "conditions": [{"field": "x", "op": "ne", "value": 0.0}]}]
        result = rule_based_classifier({"x": 1.0}, rules)
        assert "neq" in result["matched_labels"]

    @pytest.mark.academic_reference
    def test_clips_drools_rule_engine_pattern(self):
        """Standard rule engine pattern: exclusive label assignment.

        CLIPS/Drools pattern: evaluate conditions, first exclusive rule wins.
        Given: limit_up_count >= 80, broken_rate <= 0.2 -> 'super_hot' (exclusive)
               limit_up_count >= 50 -> 'hot' (exclusive)
        Expected: only 'super_hot' is winner (comes first), not 'hot'.
        """
        rules = [
            {
                "label": "super_hot",
                "conditions": [
                    {"field": "limit_up_count", "op": "gte", "value": 80},
                    {"field": "broken_rate", "op": "lte", "value": 0.2},
                ],
                "exclusive": True,
            },
            {
                "label": "hot",
                "conditions": [{"field": "limit_up_count", "op": "gte", "value": 50}],
                "exclusive": True,
            },
        ]
        result = rule_based_classifier({"limit_up_count": 90, "broken_rate": 0.15}, rules)
        assert result["exclusive_winner"] == "super_hot"
        assert "super_hot" in result["matched_labels"]
        assert "hot" in result["matched_labels"]


class TestRuleBasedVetoCheck:
    def test_empty_rules_no_veto(self):
        result = rule_based_veto_check({"x": 1.0}, [])
        assert result["triggered_vetos"] == []
        assert result["hard_veto"] is False
        assert result["soft_veto_count"] == 0

    def test_hard_veto_triggered(self):
        rules = [
            {
                "name": "ST_flag",
                "condition": {"field": "is_st", "op": "eq", "value": True},
                "severity": "hard",
            }
        ]
        result = rule_based_veto_check({"is_st": True}, rules)
        assert result["hard_veto"] is True
        assert any(v["name"] == "ST_flag" for v in result["triggered_vetos"])

    def test_soft_veto_triggered(self):
        rules = [
            {
                "name": "high_pe",
                "condition": {"field": "pe_ratio", "op": "gte", "value": 100.0},
                "severity": "soft",
            }
        ]
        result = rule_based_veto_check({"pe_ratio": 120.0}, rules)
        assert result["hard_veto"] is False
        assert result["soft_veto_count"] == 1

    def test_multiple_vetos_accumulate(self):
        rules = [
            {"name": "V1", "condition": {"field": "x", "op": "gt", "value": 0}, "severity": "soft"},
            {"name": "V2", "condition": {"field": "x", "op": "gt", "value": 0}, "severity": "soft"},
        ]
        result = rule_based_veto_check({"x": 1.0}, rules)
        assert result["soft_veto_count"] == 2

    def test_missing_field_no_trigger(self):
        rules = [
            {
                "name": "V",
                "condition": {"field": "missing", "op": "eq", "value": 1},
                "severity": "hard",
            }
        ]
        result = rule_based_veto_check({"x": 1.0}, rules)
        assert result["hard_veto"] is False

    def test_veto_not_triggered_when_condition_fails(self):
        rules = [
            {
                "name": "V",
                "condition": {"field": "x", "op": "gte", "value": 100.0},
                "severity": "hard",
            }
        ]
        result = rule_based_veto_check({"x": 50.0}, rules)
        assert result["hard_veto"] is False

    def test_mixed_hard_soft(self):
        rules = [
            {
                "name": "V1",
                "condition": {"field": "a", "op": "eq", "value": 1.0},
                "severity": "soft",
            },
            {
                "name": "V2",
                "condition": {"field": "b", "op": "eq", "value": 1.0},
                "severity": "hard",
            },
        ]
        result = rule_based_veto_check({"a": 1.0, "b": 1.0}, rules)
        assert result["hard_veto"] is True
        assert result["soft_veto_count"] == 1

    def test_veto_detail_fields(self):
        rules = [
            {"name": "V", "condition": {"field": "x", "op": "gt", "value": 0.0}, "severity": "soft"}
        ]
        result = rule_based_veto_check({"x": 1.0}, rules)
        veto = result["triggered_vetos"][0]
        assert "detail" in veto
        assert veto["detail"]["field"] == "x"

    @pytest.mark.academic_reference
    def test_a_share_market_veto_pattern(self):
        """A-share market rule veto: ST stock + limit-down block sell.

        Standard Chinese A-share risk veto pattern:
        - ST designation = hard veto (cannot trade)
        - PE > 200 = soft warning
        Facts: is_st=True, pe_ratio=250
        Expected: hard_veto=True, soft_veto_count=1
        """
        rules = [
            {
                "name": "ST_veto",
                "condition": {"field": "is_st", "op": "eq", "value": True},
                "severity": "hard",
            },
            {
                "name": "extreme_pe",
                "condition": {"field": "pe_ratio", "op": "gte", "value": 200.0},
                "severity": "soft",
            },
        ]
        result = rule_based_veto_check({"is_st": True, "pe_ratio": 250.0}, rules)
        assert result["hard_veto"] is True
        assert result["soft_veto_count"] == 1
        assert len(result["triggered_vetos"]) == 2
