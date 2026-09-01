"""LongCat-compatible long-context agent API.

The route exposes HEVI's agent contract and optional provider endpoint.  It
does not download LongCat weights and only allows explicitly selected HEVI
studio tools to execute.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.longcat import (
    LongCatConfig,
    LongCatContextBlock,
    LongCatTool,
    longcat_agent_workflow,
    longcat_capabilities,
)
from hevi.provider_policy.runtime import probe_provider
from hevi.studio.tools import get_tool, invoke_tool, list_tools

router = APIRouter(prefix="/agent/longcat", tags=["longcat"])

_SAFE_DEFAULT_TOOLS = (
    "research.plan",
    "script.quick",
    "material.rank",
    "nle.edit_plan",
    "timeline.create",
    "runtime.select",
    "delivery.preview",
    "score.provider",
)


class ContextBlockRequest(BaseModel):
    block_id: str
    text: str = Field(min_length=1)
    kind: str = "document"
    priority: float = Field(default=0.0, ge=0.0, le=1.0)
    recency: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LongCatRunRequest(BaseModel):
    goal: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    context_blocks: list[ContextBlockRequest] = Field(default_factory=list)
    model: str = "LongCat-2.0"
    max_context_tokens: int = Field(default=1_000_000, ge=1024, le=1_000_000)
    max_output_tokens: int = Field(default=4096, ge=1, le=131072)
    max_tool_rounds: int = Field(default=8, ge=0, le=32)
    enable_thinking: bool = True
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    input_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)
    output_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0)
    tool_names: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _tool_contracts(names: list[str]) -> tuple[tuple[LongCatTool, ...], dict[str, Any], list[str]]:
    selected = names or list(_SAFE_DEFAULT_TOOLS)
    tools: list[LongCatTool] = []
    handlers: dict[str, Any] = {}
    errors: list[str] = []
    for name in selected[:32]:
        spec = get_tool(name)
        if spec is None:
            errors.append(f"unknown HEVI tool: {name}")
            continue
        properties = {key: {"type": "string"} for key in spec.input_keys}
        tools.append(
            LongCatTool(
                name=spec.tool_id,
                description=spec.summary,
                parameters={"type": "object", "properties": properties},
            )
        )

        async def _handler(payload: dict[str, Any], *, _name: str = spec.tool_id) -> dict[str, Any]:
            return (await invoke_tool(_name, payload)).to_dict()

        handlers[spec.tool_id] = _handler
    return tuple(tools), handlers, errors


@router.get("/capabilities")
async def capabilities(
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    catalog = longcat_capabilities()
    catalog["hevi_tool_count"] = len(list_tools())
    catalog["default_tool_allowlist"] = list(_SAFE_DEFAULT_TOOLS)
    return catalog


@router.post("/run")
async def run_longcat(
    body: LongCatRunRequest,
    _user: Annotated[dict[str, Any] | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    provider_status = await probe_provider("longcat", timeout_s=3.0)
    if not provider_status["ready"]:
        return {
            "status": "blocked",
            "error": "LongCat-compatible provider unavailable",
            "provider": provider_status,
        }
    tools, handlers, tool_errors = _tool_contracts(body.tool_names)
    if tool_errors:
        return {"status": "blocked", "errors": tool_errors}
    config = LongCatConfig(
        model=body.model,
        max_context_tokens=body.max_context_tokens,
        max_output_tokens=body.max_output_tokens,
        max_tool_rounds=body.max_tool_rounds,
        enable_thinking=body.enable_thinking,
        temperature=body.temperature,
        input_cost_per_1k_tokens=body.input_cost_per_1k_tokens,
        output_cost_per_1k_tokens=body.output_cost_per_1k_tokens,
        tool_handlers=handlers,
    )
    context = [
        LongCatContextBlock(
            block_id=item.block_id,
            text=item.text,
            kind=item.kind,
            priority=item.priority,
            recency=item.recency,
            metadata=item.metadata,
        )
        for item in body.context_blocks
    ]
    run_dir = Path("output/longcat") / uuid.uuid4().hex
    return await longcat_agent_workflow(
        config,
        {
            "goal": body.goal,
            "messages": body.messages,
            "context_blocks": context,
            "tools": tools,
            "metadata": body.metadata,
        },
        run_dir,
    )


__all__ = ["router"]
