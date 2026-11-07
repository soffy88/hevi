"""Tests for oskill.dsl.evaluator."""

from __future__ import annotations

import pytest

from oskill.dsl.evaluator import dsl_rule_evaluate, dsl_rule_validate

# ─── Minimal valid schema for testing ────────────────────────────────────────

SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["rule_id", "triggers"],
    "properties": {
        "rule_id": {"type": "string"},
        "triggers": {"type": "array", "minItems": 1},
    },
}


class TestDslRuleValidate:
    def test_valid_rule_passes(self):
        rule = {"rule_id": "test_rule", "triggers": [{"name": "price_breakout"}]}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is True
        assert errors == []

    def test_missing_required_field_fails(self):
        rule = {"rule_id": "no_triggers"}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is False
        assert len(errors) > 0

    def test_wrong_type_fails(self):
        rule = {"rule_id": 123, "triggers": [{"name": "x"}]}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is False

    def test_empty_triggers_fails(self):
        rule = {"rule_id": "r", "triggers": []}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is False

    def test_valid_returns_empty_error_list(self):
        rule = {"rule_id": "ok", "triggers": [{"name": "x"}]}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert errors == []

    def test_error_messages_are_strings(self):
        rule = {"triggers": []}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert all(isinstance(e, str) for e in errors)

    def test_extra_properties_allowed(self):
        rule = {"rule_id": "r", "triggers": [{"name": "x"}], "extra": "val"}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is True

    @pytest.mark.academic_reference
    def test_json_schema_draft2020_12_validation(self):
        """JSON Schema Draft 2020-12 (RFC): required field validation.

        Per JSON Schema specification, missing 'required' properties must
        produce validation errors. Rule: {rule_id, triggers} required.
        Given empty dict {}, both fields missing -> invalid, 2 errors.
        """
        rule = {}
        valid, errors = dsl_rule_validate(rule, SIMPLE_SCHEMA)
        assert valid is False
        assert len(errors) >= 1  # at least one required field missing


class TestDslRuleEvaluate:
    """Async tests for dsl_rule_evaluate."""

    @pytest.mark.asyncio
    async def test_trigger_fires_and_action_executes(self):
        executed = []

        async def trigger_handler(conditions, ctx):
            return True

        async def action_handler(action, rule, matched):
            executed.append(action)

        rule_spec = {
            "trigger": {"type": "price_breakout", "conditions": {}},
            "action": {"type": "send_alert"},
        }
        result = await dsl_rule_evaluate(
            rule_spec, {}, {"price_breakout": trigger_handler}, {}, {"send_alert": action_handler}
        )
        assert result["triggered"] is True
        assert result["action_executed"] is True
        assert len(executed) == 1

    @pytest.mark.asyncio
    async def test_trigger_fails_action_not_executed(self):
        async def trigger_handler(conditions, ctx):
            return False

        rule_spec = {
            "trigger": {"type": "t1", "conditions": {}},
            "action": {"type": "a1"},
        }
        result = await dsl_rule_evaluate(rule_spec, {}, {"t1": trigger_handler}, {}, {})
        assert result["triggered"] is False
        assert result["action_executed"] is False

    @pytest.mark.asyncio
    async def test_filter_blocks_action(self):
        async def trigger_handler(conditions, ctx):
            return True

        async def filter_handler(filter_spec, ctx):
            return False

        async def action_handler(action, rule, matched):
            pass

        rule_spec = {
            "trigger": {"type": "t1", "conditions": {}},
            "filter": {"scope_type": "f1"},
            "action": {"type": "a1"},
        }
        result = await dsl_rule_evaluate(
            rule_spec, {}, {"t1": trigger_handler}, {"f1": filter_handler}, {"a1": action_handler}
        )
        assert result["triggered"] is True
        assert result["filter_passed"] is False
        assert result["action_executed"] is False

    @pytest.mark.asyncio
    async def test_no_trigger_handler_records_error(self):
        rule_spec = {"trigger": {"type": "unknown_trigger"}}
        result = await dsl_rule_evaluate(rule_spec, {}, {}, {}, {})
        assert result["triggered"] is False
        assert any("no handler" in str(t.get("error", "")) for t in result["trace"])

    @pytest.mark.asyncio
    async def test_trace_contains_stages(self):
        async def trigger_handler(conditions, ctx):
            return True

        async def action_handler(action, rule, matched):
            pass

        rule_spec = {
            "trigger": {"type": "t1", "conditions": {}},
            "action": {"type": "a1"},
        }
        result = await dsl_rule_evaluate(
            rule_spec, {}, {"t1": trigger_handler}, {}, {"a1": action_handler}
        )
        stages = {t["stage"] for t in result["trace"]}
        assert "trigger" in stages
        assert "action" in stages

    @pytest.mark.asyncio
    async def test_trigger_exception_handled(self):
        async def bad_trigger(conditions, ctx):
            raise RuntimeError("trigger exploded")

        rule_spec = {"trigger": {"type": "bad", "conditions": {}}}
        result = await dsl_rule_evaluate(rule_spec, {}, {"bad": bad_trigger}, {}, {})
        assert result["triggered"] is False
        assert any("error" in t for t in result["trace"])

    @pytest.mark.asyncio
    async def test_no_filter_handler_passes_through(self):
        async def trigger_handler(conditions, ctx):
            return True

        async def action_handler(action, rule, matched):
            pass

        rule_spec = {
            "trigger": {"type": "t1"},
            "filter": {"scope_type": "no_such_filter"},
            "action": {"type": "a1"},
        }
        result = await dsl_rule_evaluate(
            rule_spec, {}, {"t1": trigger_handler}, {}, {"a1": action_handler}
        )
        assert result["filter_passed"] is True
        assert result["action_executed"] is True

    @pytest.mark.asyncio
    async def test_no_action_handler_not_executed(self):
        async def trigger_handler(conditions, ctx):
            return True

        rule_spec = {
            "trigger": {"type": "t1"},
            "action": {"type": "no_handler_action"},
        }
        result = await dsl_rule_evaluate(rule_spec, {}, {"t1": trigger_handler}, {}, {})
        assert result["triggered"] is True
        assert result["filter_passed"] is True
        assert result["action_executed"] is False

    @pytest.mark.asyncio
    async def test_filter_exception_blocks_action(self):
        async def trigger_handler(conditions, ctx):
            return True

        async def bad_filter(filter_spec, ctx):
            raise RuntimeError("filter crashed")

        async def action_handler(action, rule, matched):
            pass

        rule_spec = {
            "trigger": {"type": "t1"},
            "filter": {"scope_type": "bad_filter"},
            "action": {"type": "a1"},
        }
        result = await dsl_rule_evaluate(
            rule_spec,
            {},
            {"t1": trigger_handler},
            {"bad_filter": bad_filter},
            {"a1": action_handler},
        )
        assert result["filter_passed"] is False
        assert result["action_executed"] is False
        assert any("error" in t for t in result["trace"] if t.get("stage") == "filter")

    @pytest.mark.asyncio
    async def test_action_exception_not_executed(self):
        async def trigger_handler(conditions, ctx):
            return True

        async def bad_action(action, rule, matched):
            raise RuntimeError("action crashed")

        rule_spec = {
            "trigger": {"type": "t1"},
            "action": {"type": "bad_action"},
        }
        result = await dsl_rule_evaluate(
            rule_spec, {}, {"t1": trigger_handler}, {}, {"bad_action": bad_action}
        )
        assert result["triggered"] is True
        assert result["action_executed"] is False
        assert any("error" in t for t in result["trace"] if t.get("stage") == "action")

    @pytest.mark.asyncio
    @pytest.mark.academic_reference
    async def test_forgy_rete_three_stage_evaluation(self):
        """Forgy (1982) Rete algorithm: three-stage pattern match -> action.

        Classic rule engine: match (trigger) -> filter -> action.
        All three stages must execute in order. Verified by execution log.
        """
        log = []

        async def trigger_handler(conditions, ctx):
            log.append("trigger")
            return True

        async def filter_handler(filter_spec, ctx):
            log.append("filter")
            return True

        async def action_handler(action, rule, matched):
            log.append("action")

        rule_spec = {
            "trigger": {"type": "match", "conditions": {}},
            "filter": {"scope_type": "scope"},
            "action": {"type": "fire"},
        }
        result = await dsl_rule_evaluate(
            rule_spec,
            {},
            {"match": trigger_handler},
            {"scope": filter_handler},
            {"fire": action_handler},
        )
        assert log == ["trigger", "filter", "action"]
        assert result["triggered"] is True
        assert result["filter_passed"] is True
        assert result["action_executed"] is True
