"""Compile HEVI request contracts into OpenAI-compatible model payloads."""

from __future__ import annotations

from typing import Any

from hevi.longcat.oprim import LongCatRequest, pack_context


def compile_longcat_request(request: LongCatRequest) -> dict[str, Any]:
    """Build a payload and an auditable context selection manifest."""

    errors = request.validate()
    if errors:
        return {
            "status": "blocked",
            "errors": errors,
            "payload": {},
            "context_manifest": {},
        }
    context = pack_context(
        request.goal,
        request.context_blocks,
        max_tokens=request.max_context_tokens,
    )
    messages = [dict(message) for message in request.messages]
    context_message = context.as_message()
    if context_message is not None:
        messages.insert(0, context_message)
    if request.goal.strip() and not any(message.get("role") == "user" for message in messages):
        messages.append({"role": "user", "content": request.goal})
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": request.max_output_tokens,
        "temperature": request.temperature,
        "enable_thinking": request.enable_thinking,
        "tools": [tool.to_openai() for tool in request.tools],
    }
    if not request.tools:
        payload.pop("tools")
    return {
        "status": "ready",
        "errors": errors,
        "payload": payload,
        "context": context,
        "context_manifest": context.to_dict(),
    }


__all__ = ["compile_longcat_request"]
