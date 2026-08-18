"""精选 OpenMontage 手艺工具可调用。"""

from __future__ import annotations

import pytest

from hevi.studio.tools import invoke_tool


@pytest.mark.asyncio
async def test_craft_and_runtime_tools() -> None:
    spec = await invoke_tool("craft.shot_spec", {"text": "智伯请地于韩康子"})
    assert spec.status == "ok"
    assert set(spec.payload["spec"]) == {
        "subject",
        "motion",
        "scene",
        "spatial",
        "camera",
    }

    broll = await invoke_tool("craft.broll", {"text": "盐税制度的抽象原则"})
    assert broll.payload["mode"] == "generate"

    taste = await invoke_tool("craft.taste", {"brief": "通鉴盐税课"})
    assert taste.payload["dials"]["pace"] == "measured"

    risk = await invoke_tool(
        "craft.slideshow_risk",
        {"shots": [{"kind": "still"}, {"kind": "still"}, {"kind": "still"}]},
    )
    assert risk.payload["risky"] is True

    site = await invoke_tool("craft.site_to_video", {"url": "https://hevi.kanpan.co"})
    assert site.payload["runtime"] == "hyperframes"

    compiled = await invoke_tool("runtime.hyperframes.compile", {"topic": "盐税"})
    assert compiled.status == "ok"
    assert "data-start" in compiled.payload["html"]
