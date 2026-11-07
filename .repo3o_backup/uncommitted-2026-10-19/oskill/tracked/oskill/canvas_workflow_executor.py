"""oskill.canvas_workflow_executor — Execute a canvas workflow via WorkflowEngine.

Uses obase.WorkflowEngine for topological ordering and concurrent layer execution,
and oprim.canvas_node_execute for per-node dispatch.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> results = asyncio.run(canvas_workflow_executor(nodes=nodes, edges=edges, executor=fn))
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from obase.workflow_engine import WorkflowEngine, WorkflowExecutionError
from oprim._hevi_types import CanvasEdge, CanvasNode
from oprim.canvas_node_execute import CanvasNodeResult, canvas_node_execute


class CanvasWorkflowError(Exception):
    """Raised when canvas workflow execution fails in rollback mode."""


async def canvas_workflow_executor(
    *,
    nodes: list[CanvasNode],
    edges: list[CanvasEdge],
    executor: Callable | None = None,
    on_error: str = "rollback",
    completed: set[str] | None = None,
) -> dict[str, CanvasNodeResult]:
    """Execute a directed canvas workflow in topological layer order.

    Args:
        nodes: All CanvasNode objects in the workflow.
        edges: All CanvasEdge objects defining dependencies (from_node_id → to_node_id).
        executor: Injected callable passed to each canvas_node_execute call.
            If None, every node fails gracefully with error="no executor".
        on_error: "rollback" (default) raises CanvasWorkflowError on first node failure;
            "continue" records the error and proceeds.
        completed: Optional pre-completed node IDs to skip (forwarded to WorkflowEngine).

    Returns:
        Dict mapping node_id → CanvasNodeResult for every executed node.

    Raises:
        CycleError: If the edge graph contains a cycle.
        CanvasWorkflowError: If on_error="rollback" and any node execution fails.
    """
    node_ids = [n.node_id for n in nodes]
    edge_pairs = [(e.from_node_id, e.to_node_id) for e in edges]

    # Raises CycleError if a cycle is detected
    layers = WorkflowEngine.topological_sort(node_ids, edge_pairs)

    # Build upstream lookup per node
    node_by_id: dict[str, CanvasNode] = {n.node_id: n for n in nodes}

    # WorkflowEngine.execute calls node_executor(node_id, upstream_outputs)
    # where upstream_outputs is the cumulative outputs dict up to that point.
    async def node_fn(node_id: str, upstream_outputs: dict[str, Any]) -> Any:
        node = node_by_id[node_id]
        # Filter to direct predecessors only
        direct_upstream: dict[str, Any] = {
            e.from_node_id: upstream_outputs.get(e.from_node_id)
            for e in edges
            if e.to_node_id == node_id
        }
        result = await canvas_node_execute(
            node=node, upstream_outputs=direct_upstream, executor=executor
        )
        if not result.success and on_error == "rollback" and executor is not None:
            raise RuntimeError(result.error or "node execution failed")
        return result

    try:
        raw = await WorkflowEngine.execute(layers, node_fn, on_error=on_error, completed=completed)
    except WorkflowExecutionError as exc:
        raise CanvasWorkflowError(
            f"Canvas workflow failed at node {exc.failed_node!r}: {exc.__cause__}"
        ) from exc

    # Normalise: WorkflowEngine.execute returns dict[node_id → return-value-of-node_fn]
    results: dict[str, CanvasNodeResult] = {}
    for nid, val in raw.items():
        if isinstance(val, CanvasNodeResult):
            results[nid] = val
        elif isinstance(val, Exception):
            node = node_by_id.get(nid)
            results[nid] = CanvasNodeResult(
                node_id=nid,
                output=None,
                node_type=node.node_type if node else "",
                success=False,
                error=str(val),
            )

    return results
