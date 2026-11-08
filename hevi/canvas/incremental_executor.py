"""Incremental canvas execution engine (canvas MVP).

What changed against the old full-graph path:

* the graph is executed from the node rows, not from the JSON mirror;
* an execute call has a scope: ``dirty`` (default) runs only stale/pending/
  failed nodes, ``selected`` runs the selected nodes plus their downstream,
  ``all`` runs everything;
* locked nodes are never run and are reported as ``locked_skipped``;
* skipped nodes seed their last output so their downstream still sees data;
* every result is followed by the per-node self-check (red/yellow/green), and
  a red node is retried once inside the same budget;
* node status, artifact, revision and cost are persisted after each node, so
  an interrupted run resumes from the node rows (nothing is executed twice for
  a video provider job that was never started).

The engine itself does no media work: it is injected with the existing node
executor (``create_node_executor``) and a reviewer.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from oprim.canvas_node_execute import CanvasNodeResult
from oprim.hevi_types import CanvasEdge, CanvasNode

from hevi.canvas import graph_diff as gd
from hevi.canvas.node_store import NodeState, NodeStore
from hevi.canvas.self_check import retry_config, review_node, status_for_review

NodeExecutor = Callable[[CanvasNode, dict[str, Any]], Awaitable[Any]]
Reviewer = Callable[..., dict[str, Any]]


@dataclass
class ExecuteOptions:
    scope: str = "dirty"
    selected_ids: list[str] = field(default_factory=list)
    on_error: str = "continue"
    max_retries: int = 1
    budget_usd: float | None = None
    llm_reviewer: Any = None
    llm_rewriter: Any = None
    vision_backend: Any = None
    enqueue_review: bool = False


@dataclass
class NodeRun:
    node_key: str
    attempts: int = 0
    review: dict[str, Any] | None = None
    output: Any = None
    success: bool = True
    error: str | None = None
    reused: bool = False


def _artifacts_ok(state: NodeState) -> bool:
    if not state.artifacts:
        return state.output is not None
    for artifact in state.artifacts:
        path = Path(str(artifact.get("path") or ""))
        if not str(path) or not path.exists():
            return False
    return True


def _text_key(config: dict[str, Any]) -> str | None:
    for key in ("content", "script_text", "prompt", "text"):
        if isinstance(config.get(key), str):
            return key
    return None


def _node_model(node: dict[str, Any]) -> CanvasNode:
    return CanvasNode.model_validate(node)


def _state_brief(states: dict[str, NodeState]) -> dict[str, dict[str, Any]]:
    return {k: s.brief() for k, s in states.items()}


def _seed_output(state: NodeState) -> Any:
    if state.output is not None:
        return state.output
    if state.artifacts:
        return {"output": state.artifacts[0]["path"], "artifacts": state.artifacts}
    return None


class IncrementalExecutor:
    def __init__(
        self,
        store: NodeStore,
        *,
        executor: NodeExecutor,
        reviewer: Reviewer = review_node,
    ) -> None:
        self._store = store
        self._executor = executor
        self._reviewer = reviewer

    async def execute(
        self,
        graph_id: str,
        graph: dict[str, Any],
        *,
        options: ExecuteOptions | None = None,
    ) -> dict[str, Any]:
        opts = options or ExecuteOptions()
        nodes_json = list(graph.get("nodes_json") or graph.get("nodes") or [])
        edges_json = list(graph.get("edges_json") or graph.get("edges") or [])
        nodes = [
            _node_model(n).model_copy(
                update={"config": {**(n.get("config") or {}), "graph_id": str(graph_id)}}
            )
            for n in nodes_json
        ]
        edges = [CanvasEdge.model_validate(e) for e in edges_json]
        node_by_id = {n.node_id: n for n in nodes}

        # Materialise when a legacy/API-created graph has no node rows yet.
        states = await self._store.load_nodes(graph_id)
        if not states:
            await self._store.sync_graph(graph_id, nodes_json, edges_json)
            states = await self._store.load_nodes(graph_id)
        # An interrupted run is safe to retry: running -> pending for this pass.
        for state in states.values():
            if state.status == gd.STATUS_RUNNING:
                state.status = gd.STATUS_PENDING
        plan = gd.compute_run_set(
            scope=opts.scope,
            node_keys=[n.node_id for n in nodes],
            edges=[e.model_dump() for e in edges],
            nodes=_state_brief(states),
            selected_ids=opts.selected_ids,
        )
        run_set = set(plan["run"])
        layers = gd.topological_layers([n.node_id for n in nodes], [e.model_dump() for e in edges])
        outputs: dict[str, Any] = {}
        for key, state in states.items():
            if key not in run_set:
                seeded = _seed_output(state)
                if seeded is not None:
                    outputs[key] = seeded

        runs: dict[str, NodeRun] = {}
        started = time.monotonic()
        for layer in layers:
            for node_key in layer:
                if node_key not in run_set:
                    continue
                node = node_by_id.get(node_key)
                if node is None:
                    continue
                upstream = {
                    e.from_node_id: outputs.get(e.from_node_id)
                    for e in edges
                    if e.to_node_id == node_key
                }
                run = await self._run_node(
                    graph_id,
                    node,
                    upstream,
                    opts,
                    outputs,
                )
                runs[node_key] = run
                outputs[node_key] = run.output
                if not run.success:
                    await self._store.mark_stale(
                        graph_id,
                        [k for k in gd.descendants([e.model_dump() for e in edges], [node_key])
                         if k not in run_set],
                    )

        # Anything downstream of a rerun node that was not part of this pass is
        # stale, even when the node itself succeeded (its inputs changed).
        changed = set(run_set)
        for key in gd.descendants([e.model_dump() for e in edges], changed):
            if key not in changed:
                await self._store.mark_stale(graph_id, [key])

        results: dict[str, Any] = {}
        for node_key, run in runs.items():
            results[node_key] = CanvasNodeResult(
                node_id=node_key,
                output=run.output,
                node_type=node_by_id[node_key].node_type,
                success=run.success,
                error=run.error or "",
            ).model_dump()
        failed = [k for k, r in runs.items() if not r.success]
        reused = [k for k, r in runs.items() if r.reused]
        elapsed = round(time.monotonic() - started, 3)
        return {
            "graph_id": graph_id,
            "status": "completed" if not failed else "partial",
            "node_count": len(nodes),
            "results": results,
            "scope": opts.scope,
            "selected_ids": opts.selected_ids,
            "ran": [k for k, r in runs.items() if not r.reused],
            "reused": reused,
            "skipped": plan["skipped"],
            "locked_skipped": plan["locked"],
            "failed": failed,
            "retries": {k: r.attempts - 1 for k, r in runs.items() if r.attempts > 1},
            "elapsed_s": elapsed,
        }

    async def _run_node(
        self,
        graph_id: str,
        node: CanvasNode,
        upstream: dict[str, Any],
        opts: ExecuteOptions,
        outputs: dict[str, Any],
    ) -> NodeRun:
        state = await self._store.get_node(graph_id, node.node_id)
        estimate = float(state.estimated_cost) if state else 0.0
        upstream_text = " ".join(
            str(v.get("output") or "") for v in upstream.values() if isinstance(v, dict)
        )
        config_fp = gd.config_fingerprint(node.model_dump())
        input_fp = gd.node_input_fingerprint(node.model_dump(), upstream)

        # Content-hash reuse (CJF impact method): in a dirty rerun, a node whose
        # own config and whose upstream *content* are unchanged keeps its
        # artifact, revision and status.  Editing sentence 2 therefore does not
        # rebuild sentence 3's branch even though the whole sentences node
        # re-emitted.  Explicit selected/all runs never reuse (the user asked).
        if (
            opts.scope == "dirty"
            and state is not None
            and state.revision > 0
            and _artifacts_ok(state)
            and isinstance(state.output, dict)
            and isinstance(state.output.get("_engine"), dict)
        ):
            engine = state.output["_engine"]
            if engine.get("config_fp") == config_fp and engine.get("input_fp") == input_fp:
                current_status = status_for_review(state.review)
                await self._store.set_status(graph_id, node.node_id, current_status)
                return NodeRun(
                    node_key=node.node_id,
                    attempts=0,
                    review=state.review,
                    output=state.output,
                    success=True,
                    reused=True,
                )

        attempts = 0
        output: Any = None
        review: dict[str, Any] | None = None
        error: str | None = None
        current = node
        while True:
            attempts += 1
            await self._store.set_status(graph_id, node.node_id, gd.STATUS_RUNNING)
            try:
                output = await self._executor(current, upstream)
                error = None
            except Exception as exc:  # a node failure never kills the graph
                output = None
                error = f"{type(exc).__name__}: {exc}"
            try:
                review = await asyncio.to_thread(
                    self._reviewer,
                    current.model_dump(),
                    output,
                    upstream_text=upstream_text,
                    llm_reviewer=opts.llm_reviewer,
                    vision_backend=opts.vision_backend,
                )
            except Exception as exc:
                review = {
                    "result": "fail",
                    "reasons": [f"自检异常：{type(exc).__name__}: {exc}"],
                    "suggested_prompt": "重新生成该节点。",
                }
            if error:
                review = {
                    "result": "fail",
                    "reasons": [error],
                    "suggested_prompt": "重试该节点；若持续失败请检查输入与执行器。",
                }
            if review.get("result") != "fail" or attempts > opts.max_retries:
                break
            next_config = retry_config(current.model_dump(), review)
            if next_config is None:
                break
            # A text node is rewritten once *from the LLM's suggestion* instead
            # of merely appending the suggestion to the prompt.
            suggestion = str(review.get("suggested_prompt") or "").strip()
            base_cfg = dict(current.config or {})
            key = _text_key(base_cfg)
            if opts.llm_rewriter is not None and key and suggestion:
                try:
                    rewritten = await asyncio.to_thread(
                        opts.llm_rewriter, base_cfg[key], suggestion, base_cfg
                    )
                except Exception:
                    rewritten = None
                if isinstance(rewritten, str) and rewritten.strip():
                    next_config = {**base_cfg, key: rewritten.strip()}
            current = current.model_copy(update={"config": next_config})
            # The retry is a new attempt of the same node, not a new graph edit.
        if isinstance(output, dict):
            output = {
                **output,
                "_engine": {
                    "config_fp": config_fp,
                    "input_fp": input_fp,
                    "content_hash": gd.output_content_hash(output),
                },
            }
        if isinstance(review, dict):
            # The deterministic verdict is always the first provider; the
            # ChatGPT queue, when enabled, only adds a later verdict beside it.
            try:
                from hevi.canvas.review_queue import review_providers

                review.setdefault("review_sources", review_providers())
            except Exception:
                review.setdefault("review_sources", ["offline_rules"])
        status = status_for_review(review)
        await self._store.save_result(
            graph_id,
            node.node_id,
            status=status,
            output=output,
            review=review,
            estimated_cost=estimate,
            actual_cost=0.0,
            pricing_key=str((node.config or {}).get("pricing_key") or "local"),
        )
        if opts.enqueue_review:
            try:
                from hevi.canvas.review_queue import enqueue_for_node, extract_sentence
                from hevi.db.pg_pool import get_hevi_pg_pool

                await enqueue_for_node(
                    await get_hevi_pg_pool(),
                    graph_id=graph_id,
                    node_key=node.node_id,
                    node_type=node.node_type,
                    sentence_text=extract_sentence(current.model_dump(), output),
                    output=output,
                    review=review,
                    node_config=current.config,
                )
            except Exception:
                # A review queue outage never fails a node that already rendered.
                import logging

                logging.getLogger(__name__).exception(
                    "canvas review queue enqueue failed for %s/%s", graph_id, node.node_id
                )
        success = review.get("result") != "fail" and error is None
        return NodeRun(
            node_key=node.node_id,
            attempts=attempts,
            review=review,
            output=output,
            success=success,
            error=error,
        )
