"""Tests for oskill.performance.rule_compliance_winrate_diff (B8)."""

from oskill.performance import rule_compliance_winrate_diff


def _rule_check_positive(trade: dict) -> bool:
    """Simple rule: compliant if pnl_pct > 0."""
    return trade.get("plan_match", False)


class TestRuleComplianceWinrateDiff:
    def test_standard_50_50_split(self) -> None:
        trades = [
            {"pnl_pct": 5.0, "plan_match": True},
            {"pnl_pct": -2.0, "plan_match": True},
            {"pnl_pct": 3.0, "plan_match": False},
            {"pnl_pct": -4.0, "plan_match": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["compliant"]["n_trades"] == 2
        assert result["violation"]["n_trades"] == 2
        assert result["n_total"] == 4
        assert result["compliant"]["winrate"] == 0.5
        assert result["violation"]["winrate"] == 0.5

    def test_all_compliant_empty_violation(self) -> None:
        trades = [
            {"pnl_pct": 5.0, "plan_match": True},
            {"pnl_pct": 3.0, "plan_match": True},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["compliant"]["n_trades"] == 2
        assert result["violation"]["n_trades"] == 0
        assert result["violation"]["winrate"] is None

    def test_all_violation_empty_compliant(self) -> None:
        trades = [
            {"pnl_pct": -1.0, "plan_match": False},
            {"pnl_pct": -2.0, "plan_match": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["compliant"]["n_trades"] == 0
        assert result["compliant"]["winrate"] is None
        assert result["violation"]["n_trades"] == 2

    def test_rule_check_fn_raises_skips_trade(self) -> None:
        def bad_rule(trade: dict) -> bool:
            if trade.get("bad"):
                raise ValueError("bad trade")
            return True

        trades = [
            {"pnl_pct": 5.0, "bad": False},
            {"pnl_pct": 3.0, "bad": True},
            {"pnl_pct": -1.0, "bad": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=bad_rule, return_field="pnl_pct"
        )
        assert len(result["errors"]) == 1
        assert result["compliant"]["n_trades"] == 2
        assert result["n_total"] == 3

    def test_single_trade_winrate_0_or_1(self) -> None:
        trades = [{"pnl_pct": 5.0, "plan_match": True}]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["compliant"]["winrate"] == 1.0

        trades_loss = [{"pnl_pct": -5.0, "plan_match": True}]
        result2 = rule_compliance_winrate_diff(
            trades=trades_loss, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result2["compliant"]["winrate"] == 0.0

    def test_diff_sign_positive_compliant_better(self) -> None:
        trades = [
            {"pnl_pct": 10.0, "plan_match": True},
            {"pnl_pct": 5.0, "plan_match": True},
            {"pnl_pct": -3.0, "plan_match": False},
            {"pnl_pct": -5.0, "plan_match": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["diff"]["winrate_pct_points"] > 0

    def test_diff_sign_negative_compliant_worse(self) -> None:
        trades = [
            {"pnl_pct": -3.0, "plan_match": True},
            {"pnl_pct": -5.0, "plan_match": True},
            {"pnl_pct": 10.0, "plan_match": False},
            {"pnl_pct": 5.0, "plan_match": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["diff"]["winrate_pct_points"] < 0

    def test_zero_trades_empty_result(self) -> None:
        result = rule_compliance_winrate_diff(
            trades=[], rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        assert result["n_total"] == 0
        assert result["compliant"]["n_trades"] == 0
        assert result["violation"]["n_trades"] == 0

    def test_nan_return_handling(self) -> None:
        trades = [
            {"pnl_pct": float("nan"), "plan_match": True},
            {"pnl_pct": 5.0, "plan_match": True},
            {"pnl_pct": float("nan"), "plan_match": False},
        ]
        result = rule_compliance_winrate_diff(
            trades=trades, rule_check_fn=_rule_check_positive, return_field="pnl_pct"
        )
        # NaN should be excluded from calculations
        assert result["compliant"]["n_trades"] == 1
        assert result["compliant"]["winrate"] == 1.0
