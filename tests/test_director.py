"""L4 导演层测试 —— Producer / Director / Editor(设计 §3 L4)。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from oprim._hevi_types import CanvasNode

from hevi.director import ProducerPlan, build_canvas_graph, produce, review


def _plan(provider: str = "wan_local") -> ProducerPlan:
    return ProducerPlan(
        topic="a fox in snow",
        duration_archetype="1-5min",
        video_provider=provider,
        audio_provider="vibevoice",
        style="cinematic",
        num_characters=1,
        estimated_usd=0.0,
        budget_usd=None,
        budget_ok=True,
        feasible=True,
    )


# ── Producer ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_producer_auto_routes_and_budget_ok():
    with (
        patch(
            "hevi.cost.router.route_video_provider",
            new_callable=AsyncMock,
            return_value="wan_cloud",
        ),
        patch(
            "hevi.director.producer.estimate_cost",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(total_usd=1.2),
        ),
    ):
        plan = await produce(
            topic="AI history", duration_archetype="1-5min", video_provider="auto", budget_usd=2.0
        )
    assert plan.video_provider == "wan_cloud"  # 成本路由选中
    assert plan.estimated_usd == 1.2
    assert plan.budget_ok is True and plan.feasible is True
    assert any("auto-routed" in n for n in plan.notes)


@pytest.mark.asyncio
async def test_producer_budget_exceeded_infeasible():
    with patch(
        "hevi.director.producer.estimate_cost",
        new_callable=AsyncMock,
        return_value=SimpleNamespace(total_usd=5.0),
    ):
        plan = await produce(
            topic="x", duration_archetype="1-5min", video_provider="wan_cloud", budget_usd=2.0
        )
    assert plan.budget_ok is False and plan.feasible is False
    assert any("预算不足" in n for n in plan.notes)


# ── Director ─────────────────────────────────────────────────────────────────


def test_director_builds_graph_structure():
    g = build_canvas_graph(plan=_plan(), shot_prompts=["a fox runs", "a fox sleeps"])
    assert len(g["nodes"]) == 3  # 1 text + 2 video
    assert len(g["edges"]) == 2
    vids = [n for n in g["nodes"] if n["node_type"] == "video"]
    assert vids[0]["config"]["prompt"] == "a fox runs"
    assert all(n["config"]["provider"] == "wan_local" for n in vids)
    assert all(n["config"]["mode"] == "t2v" for n in vids)  # 无角色锁 → t2v


def test_director_character_lock_uses_i2v():
    g = build_canvas_graph(
        plan=_plan(), shot_prompts=["hero fights"], character_reference="/ref/hero.png"
    )
    vid = next(n for n in g["nodes"] if n["node_type"] == "video")
    assert vid["config"]["mode"] == "i2v"
    assert vid["config"]["reference_image"] == "/ref/hero.png"


def test_director_empty_prompts_raises():
    with pytest.raises(ValueError):
        build_canvas_graph(plan=_plan(), shot_prompts=[])


@pytest.mark.asyncio
async def test_director_graph_executes_via_canvas():
    """§7-7 + L4:Director 产的 video 节点交 canvas executor → 走真实生成(可执行图)。"""
    from hevi.canvas.node_mapper import create_node_executor

    g = build_canvas_graph(plan=_plan(), shot_prompts=["a fox runs"])
    vid_dict = next(n for n in g["nodes"] if n["node_type"] == "video")
    vid_node = CanvasNode.model_validate(vid_dict)
    executor = create_node_executor()
    with patch(
        "hevi.video.kernel_service.generate_clip",
        new_callable=AsyncMock,
        return_value=Path("output/canvas/x.mp4"),
    ) as gen:
        res = await executor(vid_node, {"topic": {"type": "text", "output": "a fox in snow"}})
    gen.assert_awaited_once()
    assert res["type"] == "video" and res["output"] == "output/canvas/x.mp4"
    assert gen.call_args.kwargs["prompt"] == "a fox runs"  # 用节点 config 的 prompt


# ── Editor ───────────────────────────────────────────────────────────────────


def test_editor_flags_low_consistency_and_failed_shots():
    shots = [
        {"index": 0, "passed": True, "consistency_score": 0.95},
        {"index": 1, "passed": True, "consistency_score": 0.60},  # 偏低
        {"index": 2, "passed": False, "consistency_score": 0.90},  # 未过
    ]
    d = review(quality={"passed": True}, shots=shots, consistency_floor=0.75)
    assert d.regenerate_shot_ids == [1, 2]
    assert d.deliver is False
    assert 1 in d.hints and 2 in d.hints


def test_editor_delivers_when_all_good():
    d = review(
        quality={"passed": True}, shots=[{"index": 0, "passed": True, "consistency_score": 0.9}]
    )
    assert d.deliver is True
    assert d.regenerate_shot_ids == []


def test_editor_no_deliver_when_quality_failed():
    d = review(
        quality={"passed": False, "violations": ["时长偏离"]},
        shots=[{"index": 0, "passed": True, "consistency_score": 0.9}],
    )
    assert d.deliver is False
    assert any("体检不过" in r for r in d.reasons)
