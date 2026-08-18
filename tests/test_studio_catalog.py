"""OpenMontage 规模:100+ 工具可列出、可调用。"""

from __future__ import annotations

import pytest

from hevi.studio.catalog import ALL_CATALOG
from hevi.studio.tools import invoke_tool, list_tools


def test_catalog_has_over_one_hundred_tools() -> None:
    ids = {t.tool_id for t in list_tools()}
    assert len(ids) >= 100
    assert len(ALL_CATALOG) >= 70
    assert "timeline.create" in ids
    assert "timeline.split" in ids
    assert "publish.douyin" in ids
    assert "explainer.card.hook" in ids
    assert "director.camera.wide" in ids
    assert "runtime.hyperframes.compile" in ids
    assert "craft.shot_spec" in ids
    assert "daily.tick" in ids
    assert "veya.produce" in ids


@pytest.mark.asyncio
async def test_catalog_ops_run() -> None:
    pacing = await invoke_tool(
        "watch.pacing", {"transcript": "盐税发军饷。帝国靠它。", "duration_s": 20}
    )
    assert pacing.status == "ok"
    assert "pacing" in pacing.payload

    nodes = await invoke_tool("line.recipe_nodes", {"line_id": "explainer"})
    assert nodes.status == "ok"
    assert nodes.payload["nodes"]

    factory = await invoke_tool(
        "clip.factory",
        {"edit_plan": {"cuts": [{"action": "keep"}, {"action": "drop"}]}},
    )
    assert factory.payload["count"] == 1
