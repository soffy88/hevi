"""hevi.freezone.service — Freezone 装配层。

生成器注册表(装配:绑定 hevi 真实 image/video/audio 服务或测试 stub)
+ 图执行 → 候选收集 → 提升回主线。机制(graph/candidates)与装配分离。

Fail-closed: 未为节点 kind 注册 generator 时节点失败,不落 stub 候选。
可选 FreezoneStateStore 提供 FREEZONE_RESTART_RECOVERY(图 + 候选持久化)。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

from hevi.freezone.candidates import CandidatePool
from hevi.freezone.graph import FreezoneGraph, Generator, NodeResult, NodeSpec
from hevi.freezone.store import FreezoneStateStore


class UnknownGeneratorError(RuntimeError):
    """No generator registered for node kind — fail closed (no stub)."""


@dataclass
class FreezoneRun:
    run_id: str
    graph: FreezoneGraph
    results: dict[str, NodeResult] = field(default_factory=dict)
    candidate_ids: list[str] = field(default_factory=list)
    user_id: str = ""
    graph_id: str = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results.values() if r.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "graph_id": self.graph_id,
            "nodes": [
                {
                    "id": nid,
                    "ok": r.ok,
                    "error": r.error or None,
                    "output": _plain(r.output),
                }
                for nid, r in self.results.items()
            ],
            "ok_count": self.ok_count,
            "candidates": self.candidate_ids,
        }


def _plain(output: Any) -> Any:
    if isinstance(output, (str, int, float, bool)) or output is None:
        return output
    if isinstance(output, dict):
        return {k: _plain(v) for k, v in output.items()}
    if isinstance(output, (list, tuple)):
        return [_plain(v) for v in output]
    return str(output)


@dataclass
class OwnedGraph:
    graph: FreezoneGraph
    user_id: str


class FreezoneService:
    """无限画布服务:建图 → 执行 → 候选 → 提升。按 user_id 隔离。"""

    def __init__(
        self,
        generators: dict[str, Callable[..., Any]] | None = None,
        *,
        store: FreezoneStateStore | None = None,
    ) -> None:
        self.generators: dict[str, Callable[..., Any]] = {}
        if generators:
            for kind, fn in generators.items():
                self.register(kind, fn)
        self.pool = CandidatePool()
        self._runs: dict[str, FreezoneRun] = {}
        self._graphs: dict[str, OwnedGraph] = {}
        self._store = store
        if store is not None:
            self._hydrate(store.load())

    def register(self, kind: str, fn: Callable[..., Any]) -> None:
        self.generators[kind] = fn

    def _generator_for(self, node: NodeSpec) -> Generator:
        # 节点级 generator 覆盖(测试/装配注入)优先,否则按 kind 注册表。
        # Fail-closed: 未注册 kind 抛 UnknownGeneratorError → 节点失败,不进候选池。
        node_gen = node.params.pop("_generator", None)
        if node_gen is not None:
            if not callable(node_gen):
                raise UnknownGeneratorError("_generator override must be callable")
            return cast(Generator, node_gen)
        fn = self.generators.get(node.kind)
        if fn is None:
            raise UnknownGeneratorError(f"no generator registered for kind {node.kind!r}")
        return cast(Generator, fn)

    def _runner(self) -> Generator:
        async def runner(node: NodeSpec, upstream: dict[str, Any]) -> Any:
            return await self._generator_for(node)(node, upstream)

        return runner

    # ── 图注册表(带 owner;重启恢复) ──────────────────────────────
    def create_graph(self, graph: FreezoneGraph, *, user_id: str) -> str:
        gid = f"fzg_{uuid4().hex[:12]}"
        self._graphs[gid] = OwnedGraph(graph=graph, user_id=user_id)
        self._persist()
        return gid

    def get_owned_graph(self, graph_id: str, *, user_id: str) -> FreezoneGraph | None:
        rec = self._graphs.get(graph_id)
        if rec is None or rec.user_id != user_id:
            return None
        return rec.graph

    def graph_owner(self, graph_id: str) -> str | None:
        rec = self._graphs.get(graph_id)
        return rec.user_id if rec else None

    # ── 执行:拓扑序跑图,成功节点产出全部进候选池 ─────────────────
    async def run_graph(
        self,
        graph: FreezoneGraph,
        *,
        score_fn: Callable[..., Any] | None = None,
        user_id: str = "",
        graph_id: str = "",
    ) -> FreezoneRun:
        run = FreezoneRun(
            run_id=f"fz_{uuid4().hex[:12]}",
            graph=graph,
            user_id=user_id,
            graph_id=graph_id,
        )
        results = await graph.execute(self._runner())
        run.results = results
        for node_id, res in results.items():
            if res.ok:
                score = 0.0
                if score_fn is not None:
                    try:
                        score = float(score_fn(node_id, res.output))
                    except Exception:
                        score = 0.0
                cand = self.pool.add(
                    node_id=node_id,
                    kind=graph.nodes[node_id].kind,
                    output=res.output,
                    score=score,
                    user_id=user_id,
                    run_id=run.run_id,
                    graph_id=graph_id,
                )
                run.candidate_ids.append(cand.id)
        self._runs[run.run_id] = run
        self._persist()
        return run

    def get_run(self, run_id: str) -> FreezoneRun | None:
        return self._runs.get(run_id)

    def promote(self, candidate_id: str, target: str, *, user_id: str = "") -> bool:
        ok = self.pool.promote(candidate_id, target, user_id=user_id)
        if ok:
            self._persist()
        return ok

    def reject(self, candidate_id: str, *, user_id: str = "") -> bool:
        ok = self.pool.reject(candidate_id, user_id=user_id)
        if ok:
            self._persist()
        return ok

    def list_candidates(self, status: str | None = None, *, user_id: str) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.pool.list(status=status, user_id=user_id)]

    # ── 持久化(FREEZONE_RESTART_RECOVERY) ────────────────────────
    def _hydrate(self, state: dict[str, Any]) -> None:
        graphs = state.get("graphs")
        if isinstance(graphs, dict):
            for gid, row in graphs.items():
                if not isinstance(row, dict):
                    continue
                nodes_raw = row.get("nodes")
                if not isinstance(nodes_raw, list):
                    continue
                try:
                    nodes = [
                        NodeSpec(
                            id=str(n.get("id") or ""),
                            kind=str(n.get("kind") or ""),
                            params=dict(n.get("params") or {}),
                            inputs=[str(x) for x in (n.get("inputs") or [])],
                        )
                        for n in nodes_raw
                        if isinstance(n, dict) and n.get("id")
                    ]
                    graph = FreezoneGraph(nodes)
                except Exception:
                    continue
                self._graphs[str(gid)] = OwnedGraph(
                    graph=graph, user_id=str(row.get("user_id") or "")
                )
        candidates = state.get("candidates")
        if isinstance(candidates, list):
            self.pool.load_rows([c for c in candidates if isinstance(c, dict)])

    def _persist(self) -> None:
        if self._store is None:
            return
        state = {
            "graphs": {
                gid: {
                    "user_id": rec.user_id,
                    "nodes": [
                        {
                            "id": n.id,
                            "kind": n.kind,
                            "params": {k: v for k, v in n.params.items() if k != "_generator"},
                            "inputs": list(n.inputs),
                        }
                        for n in rec.graph.nodes.values()
                    ],
                }
                for gid, rec in self._graphs.items()
            },
            "candidates": self.pool.dump(),
        }
        self._store.save(state)
