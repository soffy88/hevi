"""计划级自我批判测试(HEVI 路线图 Phase4 #44)。"""

from __future__ import annotations

from oprim._hevi_types import CanvasNode

from hevi.canvas.preflight import (
    check_duration_budget,
    check_style_conflicts,
    estimate_graph_cost,
    run_preflight,
)


def _video_node(node_id: str, **config) -> CanvasNode:
    return CanvasNode(node_id=node_id, node_type="video", config=config)


def test_estimate_graph_cost_sums_video_nodes_only():
    nodes = [
        _video_node("v1", provider="veo3", duration_s=8.0),
        _video_node("v2", provider="wan_local", duration_s=5.0),  # $0/s → 不计
        CanvasNode(node_id="t1", node_type="text", config={"content": "x"}),
    ]
    cost = estimate_graph_cost(nodes)
    assert cost > 0
    # veo3 = $0.05/s * 8s = $0.40;wan_local 免费
    assert abs(cost - 0.40) < 1e-6


def test_estimate_graph_cost_unknown_provider_counts_as_zero():
    nodes = [_video_node("v1", provider="not_a_real_provider", duration_s=10.0)]
    assert estimate_graph_cost(nodes) == 0.0


def test_estimate_graph_cost_defaults_duration_when_missing():
    nodes = [_video_node("v1", provider="veo3")]  # 没给 duration_s → 默认 5.0
    assert estimate_graph_cost(nodes) == 0.05 * 5.0


def test_check_style_conflicts_flags_inconsistent_style():
    nodes = [
        _video_node("v1", style="cinematic"),
        _video_node("v2", style="cyberpunk"),
    ]
    issues = check_style_conflicts(nodes)
    assert any("style" in i for i in issues)


def test_check_style_conflicts_ignores_nodes_without_explicit_style():
    nodes = [
        _video_node("v1", style="cinematic"),
        _video_node("v2"),  # 没设 style,不参与比较
    ]
    assert check_style_conflicts(nodes) == []


def test_check_style_conflicts_passes_when_all_consistent():
    nodes = [
        _video_node("v1", color_grade="teal orange"),
        _video_node("v2", color_grade="teal orange"),
    ]
    assert check_style_conflicts(nodes) == []


def test_check_duration_budget_skips_when_no_target():
    nodes = [_video_node("v1", duration_s=5.0)]
    assert check_duration_budget(nodes, target_duration_s=None) == []


def test_check_duration_budget_flags_large_deviation():
    nodes = [_video_node("v1", duration_s=5.0)]  # 5s vs 目标 60s,比例 0.08 < 0.5
    issues = check_duration_budget(nodes, target_duration_s=60.0)
    assert len(issues) == 1
    assert "偏离过大" in issues[0]


def test_check_duration_budget_passes_within_range():
    nodes = [_video_node("v1", duration_s=25.0)]  # 25/30 = 0.83,在 [0.5, 2.0] 内
    assert check_duration_budget(nodes, target_duration_s=30.0) == []


def test_check_duration_budget_flags_no_video_nodes():
    nodes = [CanvasNode(node_id="t1", node_type="text", config={})]
    issues = check_duration_budget(nodes, target_duration_s=30.0)
    assert any("没有 video 节点" in i for i in issues)


def test_run_preflight_passes_when_within_budget():
    nodes = [_video_node("v1", provider="wan_local", duration_s=5.0)]
    report = run_preflight(nodes, budget_usd=10.0)
    assert report.passed is True
    assert report.issues == []


def test_run_preflight_fails_when_over_budget():
    nodes = [_video_node("v1", provider="veo3", duration_s=100.0)]  # $5
    report = run_preflight(nodes, budget_usd=1.0)
    assert report.passed is False
    assert any(i.severity == "error" for i in report.issues)


def test_run_preflight_warnings_do_not_fail_the_report():
    nodes = [
        _video_node("v1", style="cinematic", duration_s=5.0),
        _video_node("v2", style="cyberpunk", duration_s=5.0),
    ]
    report = run_preflight(nodes, budget_usd=None)
    assert report.passed is True  # 只有 warning,没有 error
    assert any(i.severity == "warning" for i in report.issues)
