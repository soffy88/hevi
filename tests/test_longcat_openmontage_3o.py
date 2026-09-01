"""Behavioral tests for the LongCat/OpenMontage internalisation boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.longcat import LongCatContextBlock, LongCatRequest, LongCatTool, pack_context
from hevi.longcat.oskill import execute_agent_loop
from hevi.montage import AgenticMontageConfig, agentic_montage_workflow


def test_longcat_context_pack_is_budgeted_and_stable() -> None:
    pack = pack_context(
        "database migration",
        [
            LongCatContextBlock("a", "unrelated creative notes", priority=0.1),
            LongCatContextBlock("b", "database migration checklist", priority=0.2),
            LongCatContextBlock("c", "database migration rollback", priority=0.8),
        ],
        max_tokens=8,
    )
    assert pack.used_tokens <= pack.budget_tokens
    assert pack.blocks[0].block_id == "c"
    assert pack.fingerprint
    assert "c" in pack.dropped_block_ids or len(pack.blocks) < 3


@pytest.mark.asyncio
async def test_longcat_tool_loop_preserves_reasoning_and_executes_allowlisted_tool() -> None:
    calls = 0

    async def caller(**payload: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "reasoning_content": "先读取计划",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"key":"x"}'},
                                }
                            ],
                        }
                    }
                ]
            }
        assert len(payload["messages"]) >= 3
        return {
            "choices": [
                {"message": {"content": "已完成", "reasoning_content": "工具结果已核对"}}
            ],
            "usage": {"total_tokens": 12},
        }

    request = LongCatRequest(
        goal="完成查找",
        max_context_tokens=1024,
        max_tool_rounds=2,
        tools=(LongCatTool("lookup", "查找数据", {"type": "object"}),),
    )
    result = await execute_agent_loop(request, caller, tool_handlers={"lookup": lambda args: {"status": "ok", **args}})
    assert result["status"] == "completed"
    assert result["content"] == "已完成"
    assert "工具结果已核对" in result["reasoning_content"]
    assert result["tool_calls"][0]["name"] == "lookup"


@pytest.mark.asyncio
async def test_longcat_omodul_reports_blocked_without_model_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LONGCAT_BASE_URL", raising=False)
    from hevi.longcat import LongCatConfig, longcat_agent_workflow

    result = await longcat_agent_workflow(
        LongCatConfig(max_context_tokens=1024),
        {"goal": "写一个生产计划"},
        tmp_path,
    )
    assert result["status"] == "blocked"
    assert Path(result["report_path"]).is_file()
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["pillars"] == ["fingerprint", "decision_trail", "report", "cost"]


@pytest.mark.asyncio
async def test_agentic_montage_pauses_at_human_gate_and_can_execute_with_approval(tmp_path: Path) -> None:
    paused = await agentic_montage_workflow(
        AgenticMontageConfig(pipeline="framework-smoke", execute=True),
        {"topic": "数据库迁移"},
        tmp_path / "paused",
    )
    assert paused["status"] == "paused"
    assert paused["stage"] == "research"

    completed = await agentic_montage_workflow(
        AgenticMontageConfig(pipeline="framework-smoke", execute=True, auto_approve=True),
        {"topic": "数据库迁移"},
        tmp_path / "completed",
    )
    assert completed["status"] == "completed"
    assert completed["artifacts"]["script_lines"]
    assert (tmp_path / "completed" / "checkpoints" / "research.json").is_file()
