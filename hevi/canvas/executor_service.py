from __future__ import annotations

from typing import Any

from oprim.canvas_node_execute import CanvasNodeResult
from oprim.hevi_types import CanvasEdge, CanvasNode
from oskill.canvas_workflow_executor import canvas_workflow_executor

from hevi.canvas.graph_service import GraphService
from hevi.canvas.node_mapper import create_node_executor
from hevi.canvas.preflight import PreflightError, run_preflight
from hevi.canvas.validation import validate_graph


class ExecutorService:
    """Orchestrates canvas graph execution via canvas_workflow_executor."""

    def __init__(self, graph_service: GraphService) -> None:
        self._graph_svc = graph_service

    async def execute_graph(
        self,
        graph_id: str,
        *,
        on_error: str = "rollback",
        budget_usd: float | None = None,
        target_duration_s: float | None = None,
        scope: str = "dirty",
        selected_ids: list[str] | None = None,
        max_retries: int = 1,
        llm_reviewer: Any = None,
        llm_rewriter: Any = None,
        vision_backend: Any = None,
    ) -> dict[str, Any]:
        """Load graph, validate, preflight-critique, and execute.

        Returns:
            Dict with graph_id, status, preflight report, and per-node
            CanvasNodeResult dicts.

        Raises:
            ValueError: if graph not found.
            GraphValidationError: if graph is invalid (structural).
            CycleError: if graph contains a cycle.
            PreflightError: 计划级自我批判(HEVI 路线图 Phase4 #44)发现硬性问题
                (目前只有预算超支)——执行前打回,不烧算力。
            CanvasWorkflowError: if execution fails in rollback mode.
        """
        graph = await self._graph_svc.load_graph(graph_id)
        if graph is None:
            raise ValueError(f"Graph not found: {graph_id!r}")

        raw_nodes: list[Any] = graph.get("nodes_json", []) or []
        raw_edges: list[Any] = graph.get("edges_json", []) or []

        nodes = [CanvasNode.model_validate(n) for n in raw_nodes]
        edges = [CanvasEdge.model_validate(e) for e in raw_edges]

        validate_graph(nodes, edges)

        # 计划级自我批判(#44):跟结构校验(validate_graph)不同——那是"这张图能不能
        # 跑",这里是"这张图值不值得跑"。零生成成本,发生在真花钱之前。
        preflight = run_preflight(nodes, budget_usd=budget_usd, target_duration_s=target_duration_s)
        if not preflight.passed:
            errors = [i.message for i in preflight.issues if i.severity == "error"]
            raise PreflightError("; ".join(errors))

        executor = create_node_executor()

        # Incremental node engine: one node row per step, stale-only rerun,
        # locked nodes skipped, per-node self-check + one automatic retry.
        node_store = getattr(self._graph_svc, "node_store", None)
        if node_store is not None:
            from hevi.canvas.incremental_executor import ExecuteOptions, IncrementalExecutor

            # Text nodes (script / sentences / subtitle) are reviewed by the
            # configured free LLM channel when one answers; otherwise the
            # deterministic offline rules stay in force and the node records
            # review_mode=offline_rules.
            if llm_reviewer is None:
                try:
                    from hevi.canvas import llm_review

                    built = llm_review.build()
                except Exception:
                    built = None
                if built is not None:
                    llm_reviewer, built_rewriter, _channel = built
                    if llm_rewriter is None:
                        llm_rewriter = built_rewriter

            engine = IncrementalExecutor(node_store, executor=executor)
            result = await engine.execute(
                graph_id,
                graph,
                options=ExecuteOptions(
                    scope=scope,
                    selected_ids=list(selected_ids or []),
                    on_error=on_error,
                    max_retries=max_retries,
                    budget_usd=budget_usd,
                    llm_reviewer=llm_reviewer,
                    llm_rewriter=llm_rewriter,
                    vision_backend=vision_backend,
                    enqueue_review=True,
                ),
            )
            result["node_count"] = len(nodes)
            result["preflight"] = {
                "estimated_cost_usd": preflight.estimated_cost_usd,
                "warnings": [i.message for i in preflight.issues if i.severity == "warning"],
            }
            return result

        results: dict[str, CanvasNodeResult] = await canvas_workflow_executor(
            nodes=nodes,
            edges=edges,
            executor=executor,
            on_error=on_error,
        )

        node_results: dict[str, Any] = {nid: r.model_dump() for nid, r in results.items()}
        all_success = all(r.success for r in results.values())

        return {
            "graph_id": graph_id,
            "status": "completed" if all_success else "partial",
            "node_count": len(nodes),
            "results": node_results,
            "preflight": {
                "estimated_cost_usd": preflight.estimated_cost_usd,
                "warnings": [i.message for i in preflight.issues if i.severity == "warning"],
            },
        }
