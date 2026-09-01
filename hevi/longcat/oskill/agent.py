"""Long-horizon tool loop for LongCat-compatible callers."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from hevi.longcat.oprim import LongCatRequest, ModelTurn, ToolCall, normalize_model_turn
from hevi.longcat.oskill.compiler import compile_longcat_request


class ModelCaller(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


ToolHandler = Callable[[dict[str, Any]], Any]


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


async def _call_model(caller: ModelCaller, payload: dict[str, Any]) -> Any:
    try:
        return await _await(caller(**payload))
    except TypeError as first_error:
        # A small compatibility seam for injected test/local callers that take
        # one payload object instead of OpenAI keyword arguments.
        try:
            return await _await(caller(payload))  # type: ignore[call-arg]
        except TypeError as second_error:
            raise first_error from second_error


async def _call_tool(handler: ToolHandler, arguments: dict[str, Any]) -> Any:
    return await _await(handler(arguments))


def _tool_message(call: ToolCall, result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    return {
        "role": "tool",
        "tool_call_id": call.call_id,
        "name": call.name,
        "content": str(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)),
    }


async def execute_agent_loop(
    request: LongCatRequest,
    caller: ModelCaller,
    *,
    tool_handlers: Mapping[str, ToolHandler] | None = None,
    on_step: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Run model → tool calls → model until a final answer is produced.

    Tool handlers are explicitly injected/allow-listed.  A model can request
    a tool that is not exposed, but HEVI returns a structured failure instead
    of executing arbitrary code.
    """

    compiled = compile_longcat_request(request)
    if compiled["status"] != "ready":
        return {"status": "blocked", "errors": compiled["errors"], "context": compiled["context_manifest"]}
    handlers = dict(tool_handlers or {})
    payload = dict(compiled["payload"])
    messages = list(payload["messages"])
    trail: list[dict[str, Any]] = []
    reasoning: list[str] = []
    usage: dict[str, Any] = {}
    last_turn = ModelTurn()

    for round_index in range(request.max_tool_rounds + 1):
        payload["messages"] = messages
        if on_step is not None:
            step_result = on_step({"stage": "model", "round": round_index + 1})
            if inspect.isawaitable(step_result):
                await step_result
        raw = await _call_model(caller, payload)
        last_turn = normalize_model_turn(raw)
        if last_turn.usage:
            usage = last_turn.usage
        if last_turn.reasoning_content:
            reasoning.append(last_turn.reasoning_content)
        if not last_turn.tool_calls:
            if not last_turn.content.strip():
                return {
                    "status": "failed",
                    "error": "model returned neither final content nor tool calls",
                    "rounds": round_index + 1,
                    "decision_trail": trail,
                    "context": compiled["context_manifest"],
                }
            return {
                "status": "completed",
                "content": last_turn.content,
                "reasoning_content": "\n".join(reasoning),
                "rounds": round_index + 1,
                "tool_calls": [entry for entry in trail if entry["kind"] == "tool_call"],
                "decision_trail": trail,
                "usage": usage,
                "context": compiled["context_manifest"],
            }
        if round_index >= request.max_tool_rounds:
            return {
                "status": "failed",
                "error": "max_tool_rounds_exceeded",
                "rounds": round_index + 1,
                "decision_trail": trail,
                "context": compiled["context_manifest"],
            }

        messages.append(
            {
                "role": "assistant",
                "content": last_turn.content or None,
                "tool_calls": [call.to_dict() for call in last_turn.tool_calls],
            }
        )
        for call in last_turn.tool_calls:
            trail.append({"kind": "tool_call", "round": round_index + 1, "name": call.name, "call_id": call.call_id})
            handler = handlers.get(call.name)
            if handler is None:
                result: Any = {"status": "failed", "error": f"tool not allowed: {call.name}"}
            else:
                try:
                    result = await _call_tool(handler, call.arguments)
                except Exception as exc:
                    result = {"status": "failed", "error": str(exc)}
            trail.append(
                {
                    "kind": "tool_result",
                    "round": round_index + 1,
                    "name": call.name,
                    "status": result.get("status") if isinstance(result, dict) else "ok",
                }
            )
            messages.append(_tool_message(call, result))

    return {"status": "failed", "error": "agent loop terminated unexpectedly", "decision_trail": trail}


__all__ = ["execute_agent_loop"]
