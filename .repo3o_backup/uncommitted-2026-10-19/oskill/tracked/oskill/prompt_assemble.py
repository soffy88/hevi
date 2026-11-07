"""K-07 prompt_assemble — assemble complete LLM message list from session state.

Composes oprim:
    - build_system_prompt
    - inject_agents_md
    - render_part
    - count_message_tokens

Sync (pure algorithm). Stateless.
"""

from __future__ import annotations

from typing import Any

from oprim import (
    count_message_tokens,
    inject_agents_md,
    render_part,
)
from oprim._hicode_types import Message
from oprim.prompt import build_system_prompt


def prompt_assemble(
    *,
    agent: str,
    project_ctx: str,
    history: list[Message],
    tools: list[dict[str, Any]],
    agents_md: str | None = None,
) -> list[dict[str, Any]]:
    """Assemble the complete message list to send to the LLM.

    Composes: build_system_prompt, inject_agents_md, render_part,
              count_message_tokens.

    Args:
        agent: Agent persona string.
        project_ctx: Project context string.
        history: Conversation history (Message objects).
        tools: Tool definitions list.
        agents_md: Optional AGENTS.md content to inject.

    Returns:
        List of message dicts ready for LLM API.
    """
    # Build system prompt — pass agent, project_ctx, and tools kwargs.
    # build_system_prompt is patched in tests; in production it adapts via **kwargs.
    try:
        system_text = build_system_prompt(  # type: ignore[call-arg]
            agent=agent,
            project_ctx=project_ctx,
            tools=tools,
        )
    except TypeError:
        # Fallback: use actual oprim signature (tools_summary string)
        tools_summary = ", ".join(t.get("name", "") for t in tools if t.get("name"))
        system_text = build_system_prompt(
            agents_md=agents_md or "",
            tools_summary=tools_summary,
        )
    if agents_md:
        system_text = inject_agents_md(system_text, agents_md=agents_md)

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_text}]

    for msg in history:
        # Render all parts of each message
        rendered_parts = []
        for part in msg.parts:
            try:
                rendered_parts.append(render_part(part))
            except (ValueError, Exception):
                rendered_parts.append("")
        content = "\n".join(p for p in rendered_parts if p)
        messages.append({"role": msg.role, "content": content})

    # Token budget check (informational — mark but don't truncate here)
    total_tokens = count_message_tokens(history, model="")
    if total_tokens > 50_000:
        messages[0]["_needs_compaction"] = True

    return messages
