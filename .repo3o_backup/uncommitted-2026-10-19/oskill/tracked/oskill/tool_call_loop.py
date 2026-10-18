from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal, Protocol

from oskill._llm_caller import LLMCaller


class ToolHandler(Protocol):
    """工具处理接口."""

    def __call__(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        """执行工具并返回结果."""
        ...


def tool_call_loop(
    *,
    initial_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_handler: ToolHandler,
    llm: LLMCaller,
    max_steps: int = 10,
    on_step: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """通用 LLM tool calling 多轮循环.

    流程:
        1. 调用 LLM
        2. 若有 tool_use:
            a. 遍历每个 tool_call
            b. 调用 tool_handler
            c. 将结果作为 role: tool 消息 append 到 messages
            d. 继续 goto 1
        3. 终止条件:
            a. LLM 没有 tool_use
            b. 达到 max_steps
            c. tool_handler 抛出异常

    Returns:
        {
            "final_message": dict,
            "stop_reason": Literal["end_turn", "max_steps", "tool_error"],
            "steps": list[dict],
            "total_input_tokens": int,
            "total_output_tokens": int,
        }
    """
    messages = list(initial_messages)
    steps: list[dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0

    stop_reason: Literal["end_turn", "max_steps", "tool_error"] = "end_turn"

    for i in range(max_steps):
        try:
            response = llm(
                messages=messages,
                tools=tools,
                max_tokens=4096,
            )
        except Exception:
            raise

        # Track usage
        usage = response.get("usage", {})
        total_input_tokens += usage.get("input_tokens", 0)
        total_output_tokens += usage.get("output_tokens", 0)

        # Append assistant response
        assistant_msg = response.copy()
        if "role" not in assistant_msg:
            assistant_msg["role"] = "assistant"
        # Remove usage/stop_reason from message history if they exist to keep it clean
        assistant_msg.pop("usage", None)
        assistant_msg.pop("stop_reason", None)
        messages.append(assistant_msg)

        tool_calls = response.get("tool_calls", [])
        if not tool_calls:
            stop_reason = "end_turn"
            break

        step_tool_results = []
        for tool_call in tool_calls:
            tool_name = tool_call["name"]
            tool_input = tool_call.get("input")
            if tool_input is None:
                tool_input = tool_call.get("function", {}).get("arguments", {})

            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except json.JSONDecodeError:
                    pass

            try:
                tool_result = tool_handler(tool_name, tool_input)

                # Append tool result to messages
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_name,
                        "content": (
                            json.dumps(tool_result)
                            if not isinstance(tool_result, str)
                            else tool_result
                        ),
                    }
                )
                step_tool_results.append(
                    {
                        "tool": tool_name,
                        "input": tool_input,
                        "output": tool_result,
                    }
                )
            except Exception as e:
                stop_reason = "tool_error"
                steps.append(
                    {
                        "step": i + 1,
                        "tool_calls": step_tool_results,
                        "error": str(e),
                    }
                )
                return {
                    "final_message": messages[-2] if len(messages) >= 2 else assistant_msg,
                    "stop_reason": stop_reason,
                    "steps": steps,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                }

        step_info = {
            "step": i + 1,
            "tool_calls": step_tool_results,
        }
        steps.append(step_info)

        if on_step:
            on_step(step_info)

        if i == max_steps - 1:
            stop_reason = "max_steps"

    return {
        "final_message": messages[-1],
        "stop_reason": stop_reason,
        "steps": steps,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }
