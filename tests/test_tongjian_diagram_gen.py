"""SPEC-005 §1.4 程序生成画面(地图/时间线)测试——确定性 Pillow 渲染,零外部依赖。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from hevi.tongjian.diagram_gen import render_map_diagram, render_timeline_diagram


@pytest.mark.asyncio
async def test_render_timeline_diagram_writes_valid_image(tmp_path: Path):
    output_path = tmp_path / "timeline.png"
    result = await render_timeline_diagram(
        prompt="战国秦变法时间线",
        output_path=output_path,
        seed=42,
        extra={"title": "商鞅立木", "era": "战国·秦", "year": -359},
    )
    assert output_path.exists()
    assert result["output_path"] == str(output_path)
    assert result["seed"] == 42
    with Image.open(output_path) as img:
        assert img.size == (1024, 576)


@pytest.mark.asyncio
async def test_render_map_diagram_writes_valid_image(tmp_path: Path):
    output_path = tmp_path / "nested" / "map.png"
    result = await render_map_diagram(
        prompt="战国秦地图",
        output_path=output_path,
        seed=None,
        extra={"title": "秦国疆域", "era": "战国"},
    )
    assert output_path.exists()
    assert result["seed"] == 0
    with Image.open(output_path) as img:
        assert img.size == (1024, 576)


@pytest.mark.asyncio
async def test_render_timeline_diagram_defaults_extra_and_title_to_prompt(tmp_path: Path):
    output_path = tmp_path / "timeline2.png"
    await render_timeline_diagram(prompt="无额外元数据的讲解片段", output_path=output_path)
    assert output_path.exists()
