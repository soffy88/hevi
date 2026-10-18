"""DSL rule evaluator framework (trigger / filter / action three-stage)."""

from __future__ import annotations

from collections.abc import Callable

STABILITY = "experimental"


def dsl_rule_validate(
    rule_dict: dict,
    schema: dict,
) -> tuple[bool, list[str]]:
    """Validate a DSL rule against a JSON Schema.

    Parameters
    ----------
    rule_dict : raw rule definition
    schema : JSON Schema (Draft 2020-12)

    Returns
    -------
    (is_valid, error_messages)

    Uses: jsonschema (OK at Layer 2 boundaries)
    """
    try:
        import jsonschema  # type: ignore[import]
        from jsonschema import Draft202012Validator
    except ImportError:
        return False, ["jsonschema not installed; run: pip install jsonschema"]

    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(rule_dict))
    if errors:
        return False, [e.message for e in errors]
    return True, []


async def dsl_rule_evaluate(
    rule_spec: dict,
    context: dict,
    trigger_handlers: dict[str, Callable],
    filter_handlers: dict[str, Callable],
    action_handlers: dict[str, Callable],
) -> dict:
    """Evaluate a single DSL rule end-to-end.

    Parameters
    ----------
    rule_spec : {
        "trigger": {"type": str, "conditions": dict},
        "filter": {"scope_type": str, "scope_values": list, "extra_conditions": list},
        "action": {"type": str, "channels": list, "priority": str, ...},
        ...
    }
    context : runtime context passed to handlers
    trigger_handlers : {trigger_type: async function(conditions, context) -> bool}
    filter_handlers : {filter_type: async function(filter, context) -> bool}
    action_handlers : {action_type: async function(action, rule, matched) -> None}

    Returns
    -------
    {
        "triggered": bool,
        "filter_passed": bool,
        "action_executed": bool,
        "trace": list[dict]   # evaluation steps for audit
    }

    Methodology
    -----------
    Three-stage rule evaluation pattern. Handlers are dependency-injected,
    making the evaluator market/domain-agnostic.

    Uses: oskill.classifier.rule_based.rule_based_classifier (for filter conditions)

    Reference
    ---------
    Forgy, C. L. (1982). Rete: A fast algorithm for the many pattern/many object
    pattern match problem. Artificial Intelligence, 19(1), 17-37.
    """
    trace: list[dict] = []

    # Stage 1: Trigger
    trigger_spec = rule_spec.get("trigger", {})
    trigger_type = trigger_spec.get("type", "")
    trigger_conditions = trigger_spec.get("conditions", {})

    triggered = False
    if trigger_type in trigger_handlers:
        try:
            triggered = await trigger_handlers[trigger_type](trigger_conditions, context)
            trace.append({"stage": "trigger", "type": trigger_type, "result": triggered})
        except Exception as exc:
            trace.append({"stage": "trigger", "type": trigger_type, "error": str(exc)})
    else:
        trace.append({"stage": "trigger", "type": trigger_type, "error": "no handler"})

    if not triggered:
        return {
            "triggered": False,
            "filter_passed": False,
            "action_executed": False,
            "trace": trace,
        }

    # Stage 2: Filter
    filter_spec = rule_spec.get("filter", {})
    filter_type = filter_spec.get("scope_type", "")
    filter_passed = True

    if filter_type in filter_handlers:
        try:
            filter_passed = await filter_handlers[filter_type](filter_spec, context)
            trace.append({"stage": "filter", "type": filter_type, "result": filter_passed})
        except Exception as exc:
            filter_passed = False
            trace.append({"stage": "filter", "type": filter_type, "error": str(exc)})
    else:
        trace.append({"stage": "filter", "type": filter_type, "note": "no handler, passing"})

    if not filter_passed:
        return {
            "triggered": True,
            "filter_passed": False,
            "action_executed": False,
            "trace": trace,
        }

    # Stage 3: Action
    action_spec = rule_spec.get("action", {})
    action_type = action_spec.get("type", "")
    action_executed = False

    if action_type in action_handlers:
        try:
            await action_handlers[action_type](action_spec, rule_spec, True)
            action_executed = True
            trace.append({"stage": "action", "type": action_type, "result": "executed"})
        except Exception as exc:
            trace.append({"stage": "action", "type": action_type, "error": str(exc)})
    else:
        trace.append({"stage": "action", "type": action_type, "note": "no handler"})

    return {
        "triggered": True,
        "filter_passed": True,
        "action_executed": action_executed,
        "trace": trace,
    }
