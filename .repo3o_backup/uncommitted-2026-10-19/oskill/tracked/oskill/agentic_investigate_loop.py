import json
import re
from collections.abc import Callable
from typing import Any, Literal

from obase.tool_registry import ToolRegistry
from obase.tool_registry.schema import to_anthropic_tool
from pydantic import BaseModel

from oskill._llm_caller import LLMCaller
from oskill._signal import Signal
from oskill._utils import extract_confidence


class InvestigationStep(BaseModel):
    step_no: int
    tool_called: str
    tool_input: dict[str, Any]
    tool_output: dict[str, Any]
    observation: str  # LLM 总结这步看到什么
    next_action: str  # LLM 决定下一步做什么


class InvestigationOutcome(BaseModel):
    steps_taken: int
    steps: list[InvestigationStep]
    final_conclusion: dict[str, Any]  # {root_cause_hypothesis, confidence, evidence}
    stopped_reason: Literal[
        "confidence_threshold", "max_steps", "no_more_tools", "llm_decided_stop", "error"
    ]


def agentic_investigate_loop(
    *,
    signal: Signal,
    available_tool_names: list[str],
    llm: LLMCaller,
    on_step: Callable[[dict[str, Any]], None] | None = None,
    max_steps: int = 20,
    confidence_threshold: float = 0.8,
) -> InvestigationOutcome:
    """通用 LLM agentic 调查循环 (ReAct pattern)."""
    tools_schemas = []
    for name in available_tool_names:
        meta = ToolRegistry.get(name)
        if meta:
            tools_schemas.append(to_anthropic_tool(meta))

    system_prompt = _build_system_prompt(signal, available_tool_names)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Start investigation."},
    ]

    messages[0]["content"] = f"{system_prompt}\n\n{messages[0]['content']}"

    steps: list[InvestigationStep] = []

    for step_no in range(1, max_steps + 1):
        try:
            response = llm(
                messages=messages,
                tools=tools_schemas,
                max_tokens=4096,
            )
        except Exception as e:
            return InvestigationOutcome(
                steps_taken=len(steps),
                steps=steps,
                final_conclusion={"error": str(e)},
                stopped_reason="error",
            )

        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        if not tool_calls:
            final_conclusion = _parse_final_conclusion(content)
            return InvestigationOutcome(
                steps_taken=len(steps),
                steps=steps,
                final_conclusion=final_conclusion,
                stopped_reason="llm_decided_stop",
            )

        tool_call = tool_calls[0]
        tool_name_safe = tool_call["name"]
        tool_name = tool_name_safe.replace("__", ".")
        tool_input = tool_call["input"]
        tool_id = tool_call["id"]

        meta = ToolRegistry.get(tool_name)
        if not meta:
            tool_output = {"error": f"Tool {tool_name} not found"}
        else:
            try:
                tool_output = meta.fn(**tool_input)
            except Exception as e:
                tool_output = {"error": str(e)}

        observation = _summarize_observation(tool_output)

        step = InvestigationStep(
            step_no=step_no,
            tool_called=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            observation=observation,
            next_action="",
        )
        steps.append(step)
        if on_step:
            on_step(step.model_dump())

        messages.append({"role": "assistant", "content": content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(tool_output, default=str),
                    }
                ],
            }
        )

        confidence = extract_confidence(content)
        if confidence >= confidence_threshold:
            final_conclusion = _parse_final_conclusion(content)
            return InvestigationOutcome(
                steps_taken=len(steps),
                steps=steps,
                final_conclusion=final_conclusion,
                stopped_reason="confidence_threshold",
            )

    return InvestigationOutcome(
        steps_taken=len(steps),
        steps=steps,
        final_conclusion={"root_cause_hypothesis": "Max steps reached", "confidence": 0.5},
        stopped_reason="max_steps",
    )


def _build_system_prompt(signal: Signal, tool_names: list[str]) -> str:
    return f"""You are an Aegis Root Cause Analysis Agent.
Your goal is to investigate the following signal and identify the root cause.

SIGNAL:
{signal.model_dump_json(indent=2)}

AVAILABLE TOOLS:
{", ".join(tool_names)}

INSTRUCTIONS:
1. Use the available tools to gather evidence.
2. Analyze the evidence to form hypotheses.
3. For each step, state your observation and next action.
4. When you are confident in your findings, provide a final conclusion including:
   - Root Cause Hypothesis
   - Evidence Chain (summary)
   - Confidence Score (0.0 to 1.0)
5. Format your final conclusion clearly.
"""


def _summarize_observation(tool_output: Any) -> str:
    """Simple summary of tool output for the step recording."""
    s = str(tool_output)
    if len(s) > 200:
        return s[:197] + "..."
    return s


def _parse_final_conclusion(content: Any) -> dict[str, Any]:
    text = str(content)
    conclusion = {
        "root_cause_hypothesis": "Unknown",
        "confidence": extract_confidence(content),
        "evidence": [],
    }

    match = re.search(r"Root Cause Hypothesis:\s*(.*?)(?:\s+confidence:|$|\n)", text, re.IGNORECASE)
    if match:
        conclusion["root_cause_hypothesis"] = match.group(1).strip()

    return conclusion
