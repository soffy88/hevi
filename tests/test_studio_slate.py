"""制片厂产线配方 + 工单排产。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.memory.store import MemoryStore
from hevi.studio.assets import reset_assets
from hevi.studio.recipes import get_recipe, list_recipes, parse_recipe
from hevi.studio.slate import Slate, execute_lot_task, run_slate


@pytest.fixture(autouse=True)
def _clean_assets() -> None:
    reset_assets()
    yield
    reset_assets()


def test_twelve_production_lines_loaded() -> None:
    ids = {r.id for r in list_recipes(refresh=True)}
    assert len(ids) >= 12
    assert "kinetic_promo" in ids
    assert {
        "director_pipeline",
        "explainer",
        "history_scene",
        "documentary_montage",
        "talking_head",
        "character_animation",
    } <= ids
    history = get_recipe("history_scene")
    assert history is not None
    assert history.handoff == "tongjian"
    assert history.product == "历史现场"
    drama = get_recipe("director_pipeline")
    assert drama is not None
    assert drama.handoff == "shortdrama"
    for rec in list_recipes(refresh=True):
        assert rec.tools, rec.id
        assert rec.render_runtime in {"remotion", "hyperframes", "ffmpeg"}
        assert rec.pipeline.stages
        assert rec.pipeline.stages[-1].name == "dispatch"


def test_parse_recipe_rejects_unknown_handoff() -> None:
    with pytest.raises(Exception, match="handoff"):
        parse_recipe(
            """
id: x
product: x
summary: x
handoff: banana
slots: []
tools: []
pipeline:
  name: x
  stages:
    - name: intake
      fn: hevi.studio.stages:stage_intake
"""
        )


@pytest.mark.asyncio
async def test_history_scene_slate_schedules_tongjian(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    result = await run_slate(
        Slate(
            line_id="history_scene",
            slots={
                "source_text": "智伯请地于韩康子",
                "source_name": "三家分晋",
                "memory_store": store,
            },
        )
    )
    assert result.status == "scheduled"
    assert result.product == "历史现场"
    assert result.production_order["target"] == "tongjian"
    assert result.data["video_provider"]
    assert result.data["edit_plan"]["cuts"]


@pytest.mark.asyncio
async def test_director_pipeline_requires_manuscript() -> None:
    result = await run_slate(Slate(line_id="director_pipeline", slots={"topic": "不够"}))
    assert result.status == "blocked"
    assert "manuscript" in result.missing


@pytest.mark.asyncio
async def test_explainer_and_reference_and_shorts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    exp = await run_slate(
        Slate(line_id="explainer", slots={"topic": "盐税为什么叫薪水", "memory_store": store})
    )
    assert exp.status == "scheduled"
    assert exp.production_order["target"] == "explainer"

    ref = await run_slate(
        Slate(
            line_id="reference_adapt",
            slots={
                "transcript": "先讲钩子再讲盐路。",
                "duration_s": 30,
                "memory_store": store,
            },
        )
    )
    assert ref.status == "scheduled"
    assert ref.data["concepts"]

    media = tmp_path / "final.mp4"
    media.write_bytes(b"fake")
    clip = await run_slate(
        Slate(
            line_id="shorts_clip",
            slots={
                "media_path": str(media),
                "topic": "盐税短片",
                "platforms": ["douyin"],
                "memory_store": store,
            },
        )
    )
    assert clip.status == "planned"
    assert clip.production_order["target"] == "none"
    pubs = clip.data.get("publish_results") or []
    assert pubs and pubs[0]["status"] == "handoff"
    ticket = Path(pubs[0]["payload"]["external_id"])
    assert ticket.exists()


@pytest.mark.asyncio
async def test_unknown_line_failed() -> None:
    result = await run_slate(Slate(line_id="nope", slots={}))
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_lot_adapter(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "m.db")
    out = await execute_lot_task(
        {
            "id": "task-1",
            "topic": "盐",
            "config_json": {
                "line_id": "explainer",
                "slots": {"topic": "盐", "memory_store": store},
            },
        },
        pool=None,
    )
    assert out["status"] == "completed"
    assert out["production_order"]["target"] == "explainer"
