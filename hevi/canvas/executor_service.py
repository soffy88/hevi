from __future__ import annotations

from typing import Any

from oprim._hevi_types import CanvasEdge, CanvasNode
from oprim.canvas_node_execute import CanvasNodeResult
from oskill.canvas_workflow_executor import canvas_workflow_executor

from hevi.canvas.graph_service import GraphService
from hevi.canvas.node_mapper import create_node_executor
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
    ) -> dict[str, Any]:
        """Load graph, validate, and execute via canvas_workflow_executor.

        Returns:
            Dict with graph_id, status, and per-node CanvasNodeResult dicts.

        Raises:
            ValueError: if graph not found.
            GraphValidationError: if graph is invalid.
            CycleError: if graph contains a cycle.
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

        executor = create_node_executor()
        results: dict[str, CanvasNodeResult] = await canvas_workflow_executor(
            nodes=nodes,
            edges=edges,
            executor=executor,
            on_error=on_error,
        )

        node_results: dict[str, Any] = {
            nid: r.model_dump() for nid, r in results.items()
        }
        all_success = all(r.success for r in results.values())

        return {
            "graph_id": graph_id,
            "status": "completed" if all_success else "partial",
            "node_count": len(nodes),
            "results": node_results,
        }
