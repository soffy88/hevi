"""画布场景排序器测试。

测试覆盖:
- 拓扑排序 (线性/并行/分支/环)
- 并行轨识别
- 分支点检测
- 综合分析
"""

from __future__ import annotations

import pytest

from hevi.canvas.scene_ordering import (
    analyze_canvas_structure,
    find_branching_points,
    find_parallel_tracks,
    topological_sort,
)


class TestTopologicalSort:
    """拓扑排序测试。"""

    def test_linear_graph(self) -> None:
        """测试线性图 (n1 → n2 → n3)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]

        result = topological_sort(nodes, edges)
        assert result == ["n1", "n2", "n3"]

    def test_parallel_graph(self) -> None:
        """测试并行图 (n1 → n2, n3 → n4, 无交叉)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n3", "target": "n4"},
        ]

        result = topological_sort(nodes, edges)
        # 两种合法顺序: [n1, n2, n3, n4] 或 [n1, n3, n2, n4] 等
        assert len(result) == 4
        assert set(result) == {"n1", "n2", "n3", "n4"}
        # n1 必须在 n2 前, n3 必须在 n4 前
        assert result.index("n1") < result.index("n2")
        assert result.index("n3") < result.index("n4")

    def test_branching_graph(self) -> None:
        """测试分支图 (n1 → n2, n1 → n3, 选择结构)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "n3"},
        ]

        result = topological_sort(nodes, edges)
        assert len(result) == 3
        assert result[0] == "n1"  # n1 必须在最前
        assert set(result[1:]) == {"n2", "n3"}

    def test_cycle_detection(self) -> None:
        """测试环检测 (n1 → n2 → n3 → n1)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
            {"source": "n3", "target": "n1"},  # 形成环
        ]

        with pytest.raises(ValueError, match="cycle"):
            topological_sort(nodes, edges)

    def test_empty_graph(self) -> None:
        """测试空图。"""
        result = topological_sort([], [])
        assert result == []

    def test_single_node(self) -> None:
        """测试单节点。"""
        nodes = [{"id": "n1", "type": "video"}]
        result = topological_sort(nodes, [])
        assert result == ["n1"]

    def test_diamond_graph(self) -> None:
        """测试菱形图 (n1 → n2, n1 → n3, n2 → n4, n3 → n4)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "n3"},
            {"source": "n2", "target": "n4"},
            {"source": "n3", "target": "n4"},
        ]

        result = topological_sort(nodes, edges)
        assert len(result) == 4
        assert result[0] == "n1"
        assert result[-1] == "n4"
        assert set(result[1:3]) == {"n2", "n3"}


class TestParallelTracks:
    """并行轨识别测试。"""

    def test_two_parallel_tracks(self) -> None:
        """测试两条并行轨。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},  # 轨1
            {"source": "n3", "target": "n4"},  # 轨2
        ]

        tracks = find_parallel_tracks(nodes, edges)
        assert len(tracks) == 2
        # 每条轨应该有 2 个节点
        track_lengths = sorted(len(t) for t in tracks)
        assert track_lengths == [2, 2]

    def test_single_track(self) -> None:
        """测试单条轨 (线性)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]

        tracks = find_parallel_tracks(nodes, edges)
        assert len(tracks) == 1
        assert len(tracks[0]) == 3

    def test_three_parallel_tracks(self) -> None:
        """测试三条并行轨。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
            {"id": "n5", "type": "video"},
            {"id": "n6", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},  # 轨1
            {"source": "n3", "target": "n4"},  # 轨2
            {"source": "n5", "target": "n6"},  # 轨3
        ]

        tracks = find_parallel_tracks(nodes, edges)
        assert len(tracks) == 3

    def test_merging_tracks(self) -> None:
        """测试合并相交轨 (n1 → n2, n3 → n2, 共享 n2)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n3", "target": "n2"},  # n2 是共享节点
        ]

        tracks = find_parallel_tracks(nodes, edges)
        # 应该合并为一条轨 (因为 n2 是共享的)
        assert len(tracks) == 1
        assert len(tracks[0]) == 3


class TestBranchingPoints:
    """分支点检测测试。"""

    def test_single_branch(self) -> None:
        """测试单个分支点。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "n3"},  # n1 有两个后继
        ]

        branches = find_branching_points(nodes, edges)
        assert len(branches) == 1
        assert branches[0]["node_id"] == "n1"
        assert branches[0]["branch_count"] == 2
        assert set(branches[0]["branches"]) == {"n2", "n3"}

    def test_multiple_branches(self) -> None:
        """测试多个分支点。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
            {"id": "n5", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "n3"},  # n1 分支
            {"source": "n2", "target": "n4"},
            {"source": "n2", "target": "n5"},  # n2 分支
        ]

        branches = find_branching_points(nodes, edges)
        assert len(branches) == 2
        branch_ids = {b["node_id"] for b in branches}
        assert branch_ids == {"n1", "n2"}

    def test_no_branches(self) -> None:
        """测试无分支 (线性)。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]

        branches = find_branching_points(nodes, edges)
        assert len(branches) == 0


class TestAnalyzeCanvasStructure:
    """综合分析测试。"""

    def test_linear_structure(self) -> None:
        """测试线性结构分析。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]

        result = analyze_canvas_structure(nodes, edges)
        assert result["total_nodes"] == 3
        assert result["total_edges"] == 2
        assert result["is_linear"] is True
        assert result["has_cycle"] is False
        assert len(result["parallel_tracks"]) == 1
        assert len(result["branching_points"]) == 0

    def test_parallel_structure(self) -> None:
        """测试并行结构分析。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
            {"id": "n4", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n3", "target": "n4"},
        ]

        result = analyze_canvas_structure(nodes, edges)
        assert result["is_linear"] is False
        assert len(result["parallel_tracks"]) == 2

    def test_branching_structure(self) -> None:
        """测试分支结构分析。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n1", "target": "n3"},
        ]

        result = analyze_canvas_structure(nodes, edges)
        assert result["is_linear"] is False
        assert len(result["branching_points"]) == 1

    def test_cyclic_structure(self) -> None:
        """测试环结构分析。"""
        nodes = [
            {"id": "n1", "type": "video"},
            {"id": "n2", "type": "video"},
            {"id": "n3", "type": "video"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
            {"source": "n3", "target": "n1"},  # 环
        ]

        result = analyze_canvas_structure(nodes, edges)
        assert result["has_cycle"] is True
        assert result["is_linear"] is False
