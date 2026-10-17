"""画布场景排序器 - 非线性编排支持。

功能:
1. 拓扑排序:从画布节点 + 边计算叙事顺序
2. 并行轨识别:检测多条独立叙事线
3. 分支点检测:识别选择/闪回/多线叙事结构

对标 Toonflow 的无限画布非线性编排能力,补全 Hevi 的叙事结构分析。
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NodeInfo:
    """节点信息。"""

    node_id: str
    node_type: str  # "video", "dialogue", "transition", etc.
    config: dict[str, Any]
    predecessors: list[str]  # 前驱节点 ID
    successors: list[str]  # 后继节点 ID


def _build_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[dict[str, NodeInfo], dict[str, list[str]], dict[str, list[str]]]:
    """构建图的邻接表表示。

    Returns:
        (node_info_map, adjacency_list, reverse_adjacency_list)
    """
    node_info: dict[str, NodeInfo] = {}
    adj: dict[str, list[str]] = defaultdict(list)
    rev_adj: dict[str, list[str]] = defaultdict(list)

    # 初始化节点
    for node in nodes:
        node_id = node.get("id", "")
        if not node_id:
            continue
        node_info[node_id] = NodeInfo(
            node_id=node_id,
            node_type=node.get("type", "unknown"),
            config=node.get("config", {}),
            predecessors=[],
            successors=[],
        )

    # 构建边
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        if source in node_info and target in node_info:
            adj[source].append(target)
            rev_adj[target].append(source)
            node_info[source].successors.append(target)
            node_info[target].predecessors.append(source)

    return node_info, dict(adj), dict(rev_adj)


def topological_sort(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[str]:
    """拓扑排序 - 计算叙事顺序。

    使用 Kahn 算法(BFS)。如果有环,抛出 ValueError。

    Args:
        nodes: 画布节点列表 [{"id": "n1", "type": "video", ...}, ...]
        edges: 画布边列表 [{"source": "n1", "target": "n2"}, ...]

    Returns:
        按叙事顺序排列的节点 ID 列表

    Raises:
        ValueError: 如果图中有环
    """
    node_info, adj, _ = _build_graph(nodes, edges)

    if not node_info:
        return []

    # 计算入度
    in_degree: dict[str, int] = {nid: 0 for nid in node_info}
    for source, targets in adj.items():
        for target in targets:
            in_degree[target] = in_degree.get(target, 0) + 1

    # 初始化队列 (入度为 0 的节点)
    queue = deque([nid for nid, deg in in_degree.items() if deg == 0])
    result: list[str] = []

    while queue:
        node_id = queue.popleft()
        result.append(node_id)

        for successor in adj.get(node_id, []):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                queue.append(successor)

    # 检查是否有环
    if len(result) != len(node_info):
        cycle_nodes = [nid for nid in node_info if nid not in result]
        raise ValueError(f"Graph contains cycle involving nodes: {cycle_nodes}")

    return result


def find_parallel_tracks(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[list[str]]:
    """识别并行轨 - 检测多条独立叙事线。

    算法:
    1. 找到所有入度为 0 的节点(起点)
    2. 从每个起点做 BFS/DFS,收集可达节点
    3. 如果两条轨的节点集合不相交,则它们是并行的

    Args:
        nodes: 画布节点列表
        edges: 画布边列表

    Returns:
        并行轨列表,每条轨是一个节点 ID 列表
        例如: [["n1", "n2", "n3"], ["n4", "n5"]] 表示两条并行轨
    """
    node_info, adj, rev_adj = _build_graph(nodes, edges)

    if not node_info:
        return []

    # 找到所有起点 (入度为 0)
    in_degree: dict[str, int] = {nid: 0 for nid in node_info}
    for source, targets in adj.items():
        for target in targets:
            in_degree[target] = in_degree.get(target, 0) + 1

    start_nodes = [nid for nid, deg in in_degree.items() if deg == 0]

    if not start_nodes:
        # 所有节点都有入度 → 可能有环,返回空
        logger.warning("No start nodes found, graph may contain cycles")
        return []

    # 从每个起点做 BFS,收集可达节点
    tracks: list[set[str]] = []
    for start in start_nodes:
        visited: set[str] = set()
        queue = deque([start])
        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue
            visited.add(node_id)
            for successor in adj.get(node_id, []):
                if successor not in visited:
                    queue.append(successor)
        tracks.append(visited)

    # 合并相交的轨 (如果有共享节点,说明不是真正并行)
    merged_tracks: list[set[str]] = []
    for track in tracks:
        merged = False
        for i, existing in enumerate(merged_tracks):
            if existing & track:  # 有交集
                merged_tracks[i] = existing | track
                merged = True
                break
        if not merged:
            merged_tracks.append(track)

    # 转换为列表并排序 (按拓扑序)
    result: list[list[str]] = []
    for track_set in merged_tracks:
        # 对这条轨内的节点做拓扑排序
        track_nodes = [n for n in nodes if n.get("id") in track_set]
        track_edges = [e for e in edges if e.get("source") in track_set and e.get("target") in track_set]
        try:
            sorted_track = topological_sort(track_nodes, track_edges)
            result.append(sorted_track)
        except ValueError:
            # 这条轨内有环,跳过
            logger.warning(f"Track contains cycle: {track_set}")

    return result


def find_branching_points(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """识别分支点 - 一个节点有多个后继(选择/闪回/多线叙事)。

    Args:
        nodes: 画布节点列表
        edges: 画布边列表

    Returns:
        分支点列表,每个分支点包含:
        {
            "node_id": "n1",
            "node_type": "video",
            "branches": ["n2", "n3"],  # 后继节点
            "branch_count": 2
        }
    """
    node_info, adj, _ = _build_graph(nodes, edges)

    branching_points: list[dict[str, Any]] = []

    for node_id, info in node_info.items():
        if len(info.successors) >= 2:
            branching_points.append({
                "node_id": node_id,
                "node_type": info.node_type,
                "branches": info.successors,
                "branch_count": len(info.successors),
            })

    return branching_points


def analyze_canvas_structure(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, Any]:
    """分析画布结构 - 综合报告。

    Returns:
        {
            "total_nodes": 10,
            "total_edges": 8,
            "is_linear": True,  # 是否为线性结构
            "parallel_tracks": [["n1", "n2"], ["n3", "n4"]],
            "branching_points": [{"node_id": "n1", ...}],
            "topological_order": ["n1", "n2", "n3", ...]
        }
    """
    try:
        topo_order = topological_sort(nodes, edges)
        has_cycle = False
    except ValueError:
        topo_order = []
        has_cycle = True

    parallel_tracks = find_parallel_tracks(nodes, edges)
    branching_points = find_branching_points(nodes, edges)

    # 判断是否为线性结构 (无并行轨 + 无分支点 + 无环)
    is_linear = (
        len(parallel_tracks) <= 1
        and len(branching_points) == 0
        and not has_cycle
    )

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "is_linear": is_linear,
        "has_cycle": has_cycle,
        "parallel_tracks": parallel_tracks,
        "branching_points": branching_points,
        "topological_order": topo_order,
    }
