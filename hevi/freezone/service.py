"""hevi.freezone.service — Freezone 装配层。

生成器注册表(装配:绑定 hevi 真实 image/video/audio 服务或测试 stub)
+ 图执行 → 候选收集 → 提升回主线。机制(graph/candidates)与装配分离。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

from hevi.freezone.candidates import CandidatePool
from hevi.freezone.graph import FreezoneGraph, Generator, NodeResult, NodeSpec

# 默认 stub 生成器(未装配真实服务时,产出确定性占位,便于端到端跑通)
_async = __import__("asyncio", fromlist=["sleep"])


async def _stub_generator(node: NodeSpec, upstream: dict[str, Any]) -> str:
    prompt = node.params.get("prompt", "")
    await _async.sleep(0)
    return f"[{node.kind}] {prompt} (upstream={len(upstream)})"


@dataclass
class FreezoneRun:
    run_id: str
    graph: FreezoneGraph
    results: dict[str, NodeResult] = field(default_factory=dict)
    candidate_ids: list[str] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results.values() if r.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
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


class FreezoneService:
    """无限画布服务:建图 → 执行 → 候选 → 提升。"""

    def __init__(
        self, generators: dict[str, Callable[..., Any]] | None = None
    ) -> None:
        # kind -> async (params, upstream) -> output
        self.generators: dict[str, Callable[..., Any]] = {}
        if generators:
            for kind, fn in generators.items():
                self.register(kind, fn)
        self.pool = CandidatePool()
        self._runs: dict[str, FreezoneRun] = {}

    def register(self, kind: str, fn: Callable[..., Any]) -> None:
        self.generators[kind] = fn

    def _generator_for(self, node: NodeSpec) -> Generator:
        # 节点级 generator 覆盖(测试/装配注入)优先,否则按 kind 注册表
        node_gen = node.params.pop("_generator", None)
        if node_gen is not None:
            return cast(Generator, node_gen)
        fn = self.generators.get(node.kind)
        if fn is not None:
            return cast(Generator, fn)
        return cast(Generator, _stub_generator)

    def _runner(self) -> Generator:
        # 图执行 runner: 把 node 分发到注册生成器
        async def runner(
            node: NodeSpec, upstream: dict[str, Any]
        ) -> Any:
            return await self._generator_for(node)(node, upstream)

        return runner

    # ── 执行:拓扑序跑图,成功节点产出全部进候选池 ─────────────────
    async def run_graph(
        self, graph: FreezoneGraph, *, score_fn: Callable[..., Any] | None = None
    ) -> FreezoneRun:
        run = FreezoneRun(run_id=f"fz_{uuid4().hex[:12]}", graph=graph)
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
                )
                run.candidate_ids.append(cand.id)
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: str) -> FreezoneRun | None:
        return self._runs.get(run_id)

    def promote(self, candidate_id: str, target: str) -> bool:
        return self.pool.promote(candidate_id, target)

    def reject(self, candidate_id: str) -> bool:
        return self.pool.reject(candidate_id)
