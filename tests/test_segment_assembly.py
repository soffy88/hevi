import pytest

from hevi.capabilities import segment_assembly as sa
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities import spend_brake


def _line(n):
    return "甲" * n


def _scenes(n_shots, chars=56):
    return [{
        "scene_id": "sc-1",
        "shots": [
            {"shot_id": f"s{i + 1:02d}", "text": _line(chars)}
            for i in range(n_shots)
        ],
    }]


def test_estimate_uses_prompt_compiler_convention():
    assert sa.estimate_shot_duration_s("玉兰开了") == pytest.approx(2.0)
    assert sa.estimate_shot_duration_s("你好，世界。") == pytest.approx(2.8)
    assert sa.estimate_shot_duration_s("") == 0.0


def test_split_long_line_at_semantic_pause_without_deleting():
    line = "甲" * 15 + "，" + "乙" * 15 + "。"
    parts = sa.split_long_line(line)
    assert len(parts) == 2
    assert all(sa._content_chars(p) <= 20 for p in parts)
    assert "".join(parts) == line


def test_split_long_line_hard_splits_when_no_pause():
    parts = sa.split_long_line("甲" * 45)
    assert [sa._content_chars(p) for p in parts] == [20, 20, 5]
    assert "".join(parts) == "甲" * 45


def test_plan_180_seconds_is_12_segments():
    plan = sa.plan_segments(_scenes(12))
    assert plan["segment_count"] == 12
    assert plan["total_sec"] == pytest.approx(180.0)
    assert plan["segment_count_minimum"] == 12
    assert plan["generation_nodes"] == [f"seg-{i + 1:02d}" for i in range(12)]
    assert all(s["duration_sec"] <= 15.0 for s in plan["segments"])


def test_plan_300_seconds_is_20_segments():
    plan = sa.plan_segments(_scenes(20))
    assert plan["segment_count"] == 20
    assert plan["total_sec"] == pytest.approx(300.0)
    assert plan["segment_count_minimum"] == 20


def test_single_shot_over_cap_fails_and_names_shot():
    scenes = [{"scene_id": "sc-1", "shots": [
        {"shot_id": "big", "text": "x", "duration_sec": 16.0},
    ]}]
    with pytest.raises(CapabilityError, match="big"):
        sa.plan_segments(scenes)


def test_packing_never_exceeds_cap_and_sums_shots():
    scenes = [{"scene_id": "sc-1", "shots": [
        {"shot_id": f"s{i}", "text": _line(20)} for i in range(5)
    ]}]
    plan = sa.plan_segments(scenes)
    assert [s["duration_sec"] for s in plan["segments"]] == [12.0, 12.0, 6.0]
    assert plan["total_sec"] == pytest.approx(30.0)


def test_model_limit_below_15_shrinks_cap():
    scenes = [{"scene_id": "sc-1", "shots": [
        {"shot_id": "s1", "text": _line(20)},
        {"shot_id": "s2", "text": _line(20)},
    ]}]
    plan = sa.plan_segments(scenes, model_max_sec=10.0)
    assert plan["cap_sec"] == 10.0
    assert plan["segment_count"] == 2


def test_storyboard_rows_pass_spend_brake():
    plan = sa.plan_segments(_scenes(3))
    rows = sa.to_storyboard_rows(plan)
    assert len(rows) == 3
    assert rows[0]["segment_id"] == "seg-01"
    decision = spend_brake.gate_spend(
        rows, confirmed=True, smoke_passed=True, batch_size=3
    )
    assert decision["allowed"] is True


def test_project_graph_has_one_motion_node_per_segment():
    plan = sa.plan_segments(_scenes(3))
    graph = sa.to_project_graph(plan)
    nodes = graph["nodes"]
    assert [n["node_id"] for n in nodes] == ["seg-01", "seg-02", "seg-03"]
    assert nodes[0]["inputs"] == []
    assert nodes[1]["inputs"] == ["seg-01"]
    assert all(n["type"] == "motion" for n in nodes)
