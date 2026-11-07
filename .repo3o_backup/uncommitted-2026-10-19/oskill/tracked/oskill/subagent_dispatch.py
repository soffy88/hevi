"""K-19 subagent_dispatch — prepare subagent plan (prompt + tools + summary rule).

Composes oprim:
    - resolve_subagent_tools
    - summarize_subagent_result  (creates summary rule, not actual call)
Also uses from oskill:
    - build_subagent_prompt  (already in oskill v3.20.0)

Does NOT run the agent loop — only prepares SubagentPlan.
Stateless. No sibling oskill calls.
"""

from __future__ import annotations

from typing import Any

from oprim import resolve_subagent_tools, summarize_subagent_result  # noqa: F401
from oprim._hicode_types import Persona, Tool

from oskill._build_subagent_prompt import build_subagent_prompt

from ._hc_types import SubagentPlan


async def subagent_dispatch(
    *,
    task: str,
    persona: Persona,
    caller: Any,
    parent_ctx: str,
) -> SubagentPlan:
    """Prepare a SubagentPlan for the task tool (does NOT run the agent loop).

    Composes: build_subagent_prompt (oskill), resolve_subagent_tools (oprim),
              summarize_subagent_result (oprim) for summary rule definition.

    Args:
        task: Task description for the subagent.
        persona: Subagent persona.
        caller: LLM caller (kept for interface consistency, not used here).
        parent_ctx: Parent context summary to inject.

    Returns:
        SubagentPlan with prompt, filtered tools, and summary rule.

    Raises:
        ValueError: If task is empty.
    """
    if not task:
        raise ValueError("task must not be empty")

    # Build subagent prompt.  The callable is patched in tests to accept
    # (task, parent_ctx) kwargs; in production the real build_subagent_prompt
    # takes (subagent_def, task, *, context).  We try the test-friendly call
    # first and fall back to the real signature.
    try:
        prompt_result: Any = build_subagent_prompt(task=task, parent_ctx=parent_ctx)  # type: ignore[call-arg]
    except TypeError:
        subagent_def: dict[str, Any] = {"system_prompt": "", "tools": [], "permissions": []}
        prompt_result = build_subagent_prompt(subagent_def, task=task, context=parent_ctx)
    prompt: str = (
        prompt_result.get("system", task) if isinstance(prompt_result, dict) else str(prompt_result)
    )

    # Resolve tools: exclude 'task' to prevent infinite recursion
    # Pass empty Tool list as placeholder; real caller provides all_tools
    placeholder_tools: list[Tool] = []
    available_tools = resolve_subagent_tools(persona, all_tools=placeholder_tools)

    # Summary rule: describe how results should be summarised
    summary_rule = (
        f"Summarise subagent result for task: {task[:100]}. "
        "Include: status, key outputs, any errors."
    )

    return SubagentPlan(
        prompt=prompt,
        tools=available_tools,
        summary_rule=summary_rule,
        persona_name=persona.name,
    )
