"""制片厂工具注册表 —— 真调已落地模块,失败不 raise。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.memory.store import MemoryStore
from hevi.studio.assets import reset_assets
from hevi.studio.tools import invoke_tool, list_tools


@pytest.fixture(autouse=True)
def _clean_assets() -> None:
    reset_assets()
    yield
    reset_assets()


def test_catalog_covers_composition_primitives() -> None:
    ids = {t.tool_id for t in list_tools()}
    assert {
        "research.plan",
        "watch.concepts",
        "script.quick",
        "score.provider",
        "nle.edit_plan",
        "publish.matrix",
        "asset.bind",
        "delivery.preview",
    } <= ids


@pytest.mark.asyncio
async def test_research_plan_and_score_provider() -> None:
    planned = await invoke_tool("research.plan", {"topic": "盐如何改写帝国财政"})
    assert planned.status == "ok"
    assert planned.payload["questions"]

    scored = await invoke_tool("score.provider", {"tool_name": "video/shot"})
    assert scored.status == "ok"
    assert scored.payload["winner"]["provider"]
    assert "task_fit" in scored.payload["explain"]


@pytest.mark.asyncio
async def test_script_edit_plan_and_preview_gate() -> None:
    script = await invoke_tool("script.quick", {"topic": "盐税"})
    assert script.status == "ok"
    plan = await invoke_tool("nle.edit_plan", {"script_lines": script.payload["script_lines"]})
    assert plan.status == "ok"
    cuts = plan.payload["edit_plan"]["cuts"]
    assert cuts[0]["action"] == "keep"
    assert plan.payload["edit_plan"]["total_s"] > 0

    gate = await invoke_tool("delivery.preview", {"estimate_s": 75})
    assert gate.payload["in_band"] is True
    out = await invoke_tool("delivery.preview", {"estimate_s": 20})
    assert out.payload["in_band"] is False


@pytest.mark.asyncio
async def test_watch_concepts_fallback_and_asset_bind() -> None:
    concepts = await invoke_tool(
        "watch.concepts",
        {"transcript": "盐路与税收。帝国靠盐饷发军饷。", "duration_s": 40},
    )
    assert concepts.status == "ok"
    assert len(concepts.payload["concepts"]) >= 1

    bound = await invoke_tool(
        "asset.bind",
        {
            "kind": "subject",
            "line_id": "history_scene",
            "label": "史官",
            "asset": {"role": "narrator"},
        },
    )
    assert bound.status == "ok"
    assert bound.payload["asset"]["kind"] == "subject"


@pytest.mark.asyncio
async def test_memory_roundtrip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    wrote = await invoke_tool(
        "memory.remember",
        {"store": store, "key": "ep1", "payload": {"shots": 12}},
    )
    assert wrote.status == "ok"
    hits = await invoke_tool("memory.recall", {"store": store, "query": "ep1 镜头"})
    assert hits.status == "ok"
    assert hits.payload["hits"]


@pytest.mark.asyncio
async def test_unknown_tool_failed() -> None:
    result = await invoke_tool("no.such.tool", {})
    assert result.status == "failed"
    assert "unknown tool" in result.reason
