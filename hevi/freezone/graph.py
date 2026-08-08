"""hevi.freezone.graph — Freezone 无限画布 · 节点图机制。

对标 DramaClaw Freezone(无限画布):主线流水线之外的"自由探索"双轨——
用户拖入资产生成图/视频/音频,满意候选可提升回主线。本模块承载
**纯机制**:节点 DAG 定义、拓扑执行、失败隔离,不绑定任何生成器
(生成器由装配层注入,见 service.py)。

3O 范式:机制(本模块)与装配(service.py / api 路由)分离。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

# 节点生成器契约: async (node: NodeSpec, upstream_outputs: dict[str, Any]) -> output
Generator = Callable[['NodeSpec', dict[str, Any]], Awaitable[Any]]


@dataclass
class NodeSpec:
    """画布节点:类型(kind)+ 参数 + 上游依赖。"""

    id: str
    kind: str  # "image" | "video" | "audio" | "prompt" | "style" ...
    params: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)  # 上游 node ids


@dataclass
class NodeResult:
    node_id: str
    ok: bool
    output: Any = None
    error: str = ""


class GraphCycleError(ValueError):
    """DAG 校验失败:存在环或未知依赖。"""


class FreezoneGraph:
    """节点图:拓扑排序 + 顺序执行(失败隔离)。"""

    def __init__(self, nodes: list[NodeSpec]) -> None:
        self.nodes = {n.id: n for n in nodes}
        for n in nodes:
            unknown = [u for u in n.inputs if u not in self.nodes]
            if unknown:
                raise GraphCycleError(
                    f"node {n.id!r} 依赖未知节点: {unknown}")

    # ── 拓扑排序(DAG 校验 + 环检测) ─────────────────────────────
    def topo_order(self) -> list[NodeSpec]:
        visited: dict[str, int] = {}  # 0=visiting 1=done
        order: list[NodeSpec] = []

        def visit(nid: str) -> None:
            state = visited.get(nid)
            if state == 1:
                return
            if state == 0:
                raise GraphCycleError(f"检测到环, 涉及节点 {nid!r}")
            visited[nid] = 0
            for up in self.nodes[nid].inputs:
                visit(up)
            visited[nid] = 1
            order.append(self.nodes[nid])

        for nid in self.nodes:
            visit(nid)
        return order

    # ── 执行:按拓扑序,每节点失败不影响其他节点 ──────────────────
    async def execute(
        self, generator: Generator
    ) -> dict[str, NodeResult]:
        results: dict[str, NodeResult] = {}
        for node in self.topo_order():
            upstream = {
                u: results[u].output
                for u in node.inputs
                if u in results and results[u].ok
            }
            try:
                out = await generator(node, upstream)
                results[node.id] = NodeResult(
                    node_id=node.id, ok=True, output=out)
            except Exception as exc:
                results[node.id] = NodeResult(
                    node_id=node.id, ok=False, error=str(exc))
        return results

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": n.id, "kind": n.kind,
                    "params": n.params, "inputs": n.inputs,
                }
                for n in self.nodes.values()
            ]
        }
