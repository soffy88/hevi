"""HEVI-owned LongCat agent workflow."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.longcat.oprim import LongCatContextBlock, LongCatRequest, LongCatTool
from hevi.longcat.oservi import build_longcat_caller, longcat_provider_status
from hevi.longcat.oskill import execute_agent_loop

logger = logging.getLogger(__name__)


@dataclass
class LongCatConfig:
    model: str = "LongCat-2.0"
    max_context_tokens: int = 1_000_000
    max_output_tokens: int = 4096
    max_tool_rounds: int = 8
    enable_thinking: bool = True
    temperature: float = 0.2
    input_cost_per_1k_tokens: float = 0.0
    output_cost_per_1k_tokens: float = 0.0
    caller: Any = None
    tool_handlers: dict[str, Any] | None = None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        raw = value.model_dump()
        return dict(raw) if isinstance(raw, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _blocks(raw: Any) -> tuple[LongCatContextBlock, ...]:
    out: list[LongCatContextBlock] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, LongCatContextBlock):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "")
        if text:
            out.append(
                LongCatContextBlock(
                    block_id=str(item.get("block_id") or item.get("id") or f"block-{index + 1}"),
                    text=text,
                    kind=str(item.get("kind") or "document"),
                    priority=float(item.get("priority") or 0.0),
                    recency=float(item.get("recency") or 0.0),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
    return tuple(out)


def _tools(raw: Any) -> tuple[LongCatTool, ...]:
    out: list[LongCatTool] = []
    for item in raw or []:
        if isinstance(item, LongCatTool):
            out.append(item)
        elif isinstance(item, dict):
            function = item.get("function") if item.get("type") == "function" else item
            if isinstance(function, dict) and function.get("name"):
                out.append(
                    LongCatTool(
                        name=str(function["name"]),
                        description=str(function.get("description") or ""),
                        parameters=dict(function.get("parameters") or {"type": "object", "properties": {}}),
                    )
                )
    return tuple(out)


def _fingerprint(request: LongCatRequest) -> str:
    shape = {
        "model": request.model,
        "message_roles": [str(item.get("role") or "") for item in request.messages],
        "block_shapes": [(item.block_id, item.kind, len(item.text)) for item in request.context_blocks],
        "tools": [item.name for item in request.tools],
        "max_context_tokens": request.max_context_tokens,
        "max_tool_rounds": request.max_tool_rounds,
    }
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:24]


async def _notify(on_step: Any, event: dict[str, Any]) -> None:
    if on_step is None:
        return
    result = on_step(event)
    if inspect.isawaitable(result):
        await result


def _write_report(path: Path, body: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def longcat_agent_workflow(
    config: LongCatConfig | dict[str, Any],
    input_data: dict[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """Execute a LongCat-compatible agent transaction.

    The transaction owns report/fingerprint/trail/cost fields.  It does not
    persist user context into the fingerprint and it never returns fake model
    content when no provider is configured.
    """

    cfg = _mapping(config)
    data = _mapping(input_data)
    out = Path(output_dir)
    report_path = out / "longcat_report.json"
    pillars = ["fingerprint", "decision_trail", "report", "cost"]
    try:
        request = LongCatRequest(
            goal=str(data.get("goal") or data.get("prompt") or ""),
            messages=tuple(item for item in (data.get("messages") or ()) if isinstance(item, dict)),
            context_blocks=_blocks(data.get("context_blocks") or data.get("context")),
            model=str(cfg.get("model") or data.get("model") or "LongCat-2.0"),
            max_context_tokens=_as_int(cfg.get("max_context_tokens"), 1_000_000),
            max_output_tokens=_as_int(cfg.get("max_output_tokens"), 4096),
            max_tool_rounds=_as_int(cfg.get("max_tool_rounds"), 8),
            enable_thinking=bool(cfg.get("enable_thinking", True)),
            temperature=_as_float(cfg.get("temperature"), 0.2),
            tools=_tools(data.get("tools") or cfg.get("tools")),
            metadata=dict(data.get("metadata") or {}),
        )
        fingerprint = _fingerprint(request)
        errors = request.validate()
        if errors:
            result: dict[str, Any] = {"status": "blocked", "errors": errors, "fingerprint": fingerprint}
            _write_report(report_path, {**result, "pillars": pillars})
            return {**result, "report_path": str(report_path), "decision_trail": [], "cost_usd": 0.0}

        caller = cfg.get("caller") or data.get("caller") or build_longcat_caller()
        if caller is None:
            status = longcat_provider_status()
            result = {
                "status": "blocked",
                "error": "no LongCat-compatible provider configured",
                "provider": status,
                "fingerprint": fingerprint,
                "decision_trail": [],
                "cost_usd": 0.0,
            }
            _write_report(report_path, {**result, "pillars": pillars})
            return {**result, "report_path": str(report_path)}

        await _notify(on_step, {"stage": "context_pack", "progress_pct": 10.0})
        loop_result = await execute_agent_loop(
            request,
            caller,
            tool_handlers=cfg.get("tool_handlers") or data.get("tool_handlers") or {},
            on_step=on_step,
        )
        usage = loop_result.get("usage") or {}
        prompt_tokens = float(usage.get("prompt_tokens") or usage.get("input_tokens") or 0.0)
        completion_tokens = float(usage.get("completion_tokens") or usage.get("output_tokens") or 0.0)
        input_rate = _as_float(
            cfg.get("input_cost_per_1k_tokens")
            or data.get("input_cost_per_1k_tokens")
            or os.getenv("LONGCAT_INPUT_COST_PER_1K", "0"),
            0.0,
        )
        output_rate = _as_float(
            cfg.get("output_cost_per_1k_tokens")
            or data.get("output_cost_per_1k_tokens")
            or os.getenv("LONGCAT_OUTPUT_COST_PER_1K", "0"),
            0.0,
        )
        cost_usd = round(prompt_tokens / 1000 * input_rate + completion_tokens / 1000 * output_rate, 6)
        result = {
            **loop_result,
            "fingerprint": fingerprint,
            "provider": longcat_provider_status(),
            "pillars": pillars,
            "report_path": str(report_path),
            "cost_usd": cost_usd,
            "usage": {**usage, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        }
        _write_report(report_path, result)
        return result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("longcat_agent_workflow failed")
        result = {
            "status": "failed",
            "error": str(exc),
            "pillars": pillars,
            "report_path": str(report_path),
            "decision_trail": [],
            "cost_usd": 0.0,
        }
        _write_report(report_path, result)
        return result


def longcat_capabilities() -> dict[str, Any]:
    provider = longcat_provider_status()
    return {
        "id": "longcat_agent",
        "available": provider["available"],
        "status": "available" if provider["available"] else "unavailable",
        "context_limit_tokens": 1_000_000,
        "features": [
            "long_context_packing",
            "reasoning_content",
            "multi_round_tool_loop",
            "structured_tool_calls",
            "long_horizon_execution",
            "gpu_npu_provider_boundary",
        ],
        "provider": provider,
        "honest_boundary": "LSA/MTP/N-gram are model-kernel capabilities; HEVI owns the context/tool execution contract, not the upstream weights.",
    }


__all__ = ["LongCatConfig", "longcat_agent_workflow", "longcat_capabilities"]
