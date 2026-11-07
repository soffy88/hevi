"""synthesize_action_plan — LLM-based action plan synthesis from signal + runbook context.

Composition:
    retrieve_runbook → [runbook context]
    classify_signal  → [signal class]
    compute_severity_score → [severity]
    LLM call         → [{plugin_id, params, description}]

Used by ActionPlannerEngine (oservice) as llm_provider injection.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


class ActionStep(BaseModel):
    step_number: int
    plugin_id: str
    params: dict[str, Any]
    description: str
    rationale: str


class ActionPlanResult(BaseModel):
    symptom: str
    signal_class: str | None
    severity_score: float | None
    steps: list[ActionStep]
    context_used: str
    llm_reasoning: str | None


def synthesize_action_plan(
    *,
    symptom: str,
    llm_fn: Callable[..., Any],
    runbook_context: str = "",
    signal_class: str | None = None,
    severity_score: float | None = None,
    available_plugins: list[str] | None = None,
    max_steps: int = 5,
) -> ActionPlanResult:
    """LLM 行动计划合成 — 输入症状 + 上下文 → 结构化行动步骤列表.

    Composition note: Designed to be called after retrieve_runbook and
    classify_signal. LLM output is parsed to ActionStep list.
    Result feeds directly into ActionPlannerEngine plugin dispatch.

    Args:
        symptom: 故障症状描述
        llm_fn: LLM callable — (prompt: str) → str (raw LLM response)
                Expected to return JSON array of steps or plain text plan
        runbook_context: retrieve_runbook 返回的 runbook 内容 (可为空)
        signal_class: classify_signal 返回的信号类别
        severity_score: compute_severity_score 返回的评分 (0–100)
        available_plugins: 可用 plugin_id 列表 (提示 LLM 选择范围)
        max_steps: 最大步骤数

    Returns:
        ActionPlanResult
    """
    context_parts = []
    if signal_class:
        context_parts.append(f"Signal class: {signal_class}")
    if severity_score is not None:
        context_parts.append(f"Severity score: {severity_score}/100")
    if runbook_context:
        context_parts.append(f"Runbook context:\n{runbook_context}")
    if available_plugins:
        context_parts.append(f"Available plugins: {', '.join(available_plugins)}")

    context_str = "\n".join(context_parts)

    prompt = (
        f"You are an SRE action planner. Given the following symptom and context, "
        f"produce a JSON array of remediation steps (max {max_steps}).\n\n"
        f"Symptom: {symptom}\n\n"
        f"Context:\n{context_str}\n\n"
        f'Each step must be a JSON object with: {{"plugin_id": str, "params": dict, '
        f'"description": str, "rationale": str}}.\n'
        f"Return ONLY a JSON array. No prose."
    )

    raw_response = llm_fn(prompt)
    reasoning = None
    steps: list[ActionStep] = []

    if isinstance(raw_response, list):
        raw_steps = raw_response
    else:
        raw_text = str(raw_response)
        reasoning = raw_text
        # Try to extract JSON array from response
        try:
            start = raw_text.find("[")
            end = raw_text.rfind("]") + 1
            if start >= 0 and end > start:
                raw_steps = json.loads(raw_text[start:end])
            else:
                raw_steps = []
        except (json.JSONDecodeError, ValueError):
            raw_steps = []

    for i, step in enumerate(raw_steps[:max_steps]):
        if isinstance(step, dict):
            steps.append(
                ActionStep(
                    step_number=i + 1,
                    plugin_id=str(step.get("plugin_id", "")),
                    params=dict(step.get("params", {})),
                    description=str(step.get("description", "")),
                    rationale=str(step.get("rationale", "")),
                )
            )

    return ActionPlanResult(
        symptom=symptom,
        signal_class=signal_class,
        severity_score=severity_score,
        steps=steps,
        context_used=context_str,
        llm_reasoning=reasoning,
    )
