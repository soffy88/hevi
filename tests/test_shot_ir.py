"""统一分镜 IR(shot_ir)转换器测试:四套 schema → ShotIR 往返。"""

from __future__ import annotations

from hevi.assembly.freevideo.storyboard import FramePlan, plan_from_text
from hevi.storygraph.shot_ir import (
    ShotIR,
    from_frame_plan,
    from_recipe_card,
    from_storyboard_node,
    from_tongjian_shot,
    topo_sort,
)


def test_from_frame_plan_roundtrip():
    plans = plan_from_text("第一句讲背景。第二句讲方法。第三句讲结果。", title="T")
    ir = from_frame_plan(plans, title="demo")
    assert len(ir.nodes) == len(plans)
    assert ir.synopsis == "demo"
    # 节点字段透传
    assert ir.nodes[0].kind == "title"
    assert ir.nodes[0].body == plans[0].body
    # 序列边
    assert len(ir.edges) == len(plans) - 1
    assert all(e["kind"] == "sequence" for e in ir.edges)
    # 总时长 = 各帧和
    assert ir.total_duration_s == sum(p.duration for p in plans)


def test_from_recipe_card():
    cards = [
        {"name": "spotlight-hero", "purpose": "开场", "suggested_duration_s": 3.0,
         "params": {"hold_s": 1.0}},
        {"name": "row-embed", "purpose": "数据", "suggested_duration_s": 1.5,
         "params": {"reveal": "row-by-row"}},
    ]
    ir = from_recipe_card(cards, title="promo")
    assert ir.intent == "promo"
    assert ir.nodes[0].kind == "scene"
    assert ir.nodes[0].data == {"hold_s": 1.0}
    assert ir.nodes[1].duration_sec == 1.5


def test_from_tongjian_shot():
    shots = [
        {"scene_id": "s1", "location": "洞穴", "camera": "push-in", "duration_s": 5},
        {"scene_id": "s2", "location": "旷野", "camera": "wide", "duration_s": 4},
    ]
    ir = from_tongjian_shot(shots, title="tj")
    assert ir.nodes[0].data["location"] == "洞穴"
    assert ir.nodes[0].data["camera"] == "push-in"
    assert ir.nodes[1].duration_sec == 4.0


def test_from_storyboard_node_detects_data_kind():
    nodes = [
        {"scene_id": "n1", "caption": "用户增长 50%", "duration": 4},
        {"scene_id": "n2", "caption": "讲述方法", "duration": 3},
    ]
    ir = from_storyboard_node(nodes, title="m")
    assert ir.nodes[0].kind == "data"  # 含"增长/百分比" → data
    assert ir.nodes[1].kind == "scene"


def test_topological_order_is_stable():
    from hevi.storygraph.shot_ir import ShotNode

    ir = ShotIR(intent="explainer")
    ir.add(ShotNode(id="title", kind="title", title="A", body="a", duration_sec=3))
    ir.add(ShotNode(id="quote", kind="quote", title="B", body="b", duration_sec=4))
    ir.add(ShotNode(id="scene", kind="scene", title="C", body="c", duration_sec=5))
    ir.sequence("title", "quote")
    ir.sequence("quote", "scene")
    assert topo_sort(ir) == ["title", "quote", "scene"]


def test_to_json_serializable():
    ir = from_frame_plan([FramePlan(kind="quote", title="T", body="B", duration=4)])
    import json

    parsed = json.loads(ir.to_json())
    assert parsed["nodes"][0]["kind"] == "quote"


# ── editor.review 错配门槛(第 4 项降本) ──────────────────────────────────


def test_editor_review_min_rework_count():
    from hevi.director.editor import review

    # 软错配(score<floor 但 passed=True)才受门槛约束。
    shots = [
        {"index": 0, "passed": True, "consistency_score": 0.4},
        {"index": 1, "passed": True, "consistency_score": 0.9},
    ]
    # 默认门槛 1:1 镜软错配也返工(保持既有行为)
    d1 = review(quality={"passed": True}, shots=shots, consistency_floor=0.75)
    assert d1.regenerate_shot_ids == [0]
    # 门槛 2:1 镜软错配 < 2 → 不返工,只记录诊断
    d2 = review(
        quality={"passed": True}, shots=shots,
        consistency_floor=0.75, min_rework_count=2,
    )
    assert d2.regenerate_shot_ids == []
    assert d2.deliver is True
    assert 0 in d2.diagnosis


def test_editor_review_hard_failure_always_reworks():
    from hevi.director.editor import review

    # passed=False(黑帧/全废)是硬信号,即使低于门槛也必须返工。
    shots = [{"index": 0, "passed": False, "consistency_score": 0.1}]
    d = review(
        quality={"passed": True}, shots=shots,
        consistency_floor=0.75, min_rework_count=5,
    )
    assert d.regenerate_shot_ids == [0]


def test_editor_review_rework_when_widespread():
    from hevi.director.editor import review

    shots = [
        {"index": i, "passed": False, "consistency_score": 0.3} for i in range(5)
    ]
    # 大面积错配(5 镜)即使门槛 3 也要返工
    d = review(
        quality={"passed": True}, shots=shots,
        consistency_floor=0.75, min_rework_count=3,
    )
    assert d.regenerate_shot_ids == [0, 1, 2, 3, 4]
