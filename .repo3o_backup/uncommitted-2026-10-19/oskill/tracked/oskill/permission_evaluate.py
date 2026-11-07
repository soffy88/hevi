"""K-17 permission_evaluate — comprehensive permission decision engine.

Composes oprim:
    - resolve_agent_permissions
    - match_wildcard_pattern
    - match_bash_command_rule
    - classify_risk
Also uses from oskill:
    - match_permission_rule  (already in oskill v3.20.0)

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from typing import Any

from oprim import (
    classify_risk,
    match_bash_command_rule,
    match_wildcard_pattern,  # noqa: F401
    resolve_agent_permissions,
)
from oprim._hicode_types import Decision, Persona, Rule, ToolCall

from oskill._match_permission_rule import match_permission_rule


def permission_evaluate(
    call: ToolCall,
    *,
    rules: list[Rule],
    persona: Persona,
) -> Decision:
    """Evaluate a ToolCall against rules and persona to produce a Decision.

    Composes: resolve_agent_permissions, match_permission_rule (oskill),
              match_wildcard_pattern, match_bash_command_rule, classify_risk.

    Args:
        call: The tool call to evaluate.
        rules: Ordered list of permission rules.
        persona: Agent persona defining default permissions.

    Returns:
        Decision: 'allow', 'ask', or 'deny'.
    """
    # 1. classify risk level
    risk = classify_risk(call)

    # 2. resolve persona base permissions
    all_tools_mock: list[Any] = [type("T", (), {"name": call.name})()]
    perm_set = resolve_agent_permissions(persona, all_tools=all_tools_mock)
    persona_action: Decision = perm_set.tool_actions.get(call.name, "ask")

    # 3. match against rules (oskill existing)
    rule_action_raw = match_permission_rule(
        {"name": call.name, "args": call.args},
        allowed_tools=[r.pattern for r in rules if r.action == "allow"],
        denied_tools=[r.pattern for r in rules if r.action == "deny"],
    )
    # normalize to Decision
    if rule_action_raw in ("allow", "ask", "deny"):
        rule_action: Decision = rule_action_raw  # type: ignore[assignment]
    else:
        rule_action = "ask"

    # 4. bash-level check
    bash_action: Decision = "ask"
    if call.name == "bash":
        cmd = call.args.get("command", "")
        if cmd:
            bash_action = match_bash_command_rule(cmd, rules=perm_set.bash_rules)

    # 5. deny wins
    if "deny" in (persona_action, rule_action, bash_action):
        return "deny"

    # 6. risk upgrade: high risk → ask at minimum
    if risk == "high" and rule_action == "allow" and persona_action == "allow":
        return "ask"

    # 7. most permissive among non-deny
    for action in (rule_action, persona_action):
        if action == "allow":
            return "allow"

    return "ask"
