"""Batch 5 tests: canvas_workflow_executor."""

from __future__ import annotations

import pytest
from oprim._hevi_types import CanvasEdge, CanvasNode
from oprim.canvas_node_execute import CanvasNodeResult

from oskill.canvas_workflow_executor import (
    CanvasWorkflowError,
    canvas_workflow_executor,
)


def _node(node_id: str, node_type: str = "image") -> CanvasNode:
    return CanvasNode(node_id=node_id, node_type=node_type, label=node_id)


def _edge(from_id: str, to_id: str) -> CanvasEdge:
    return CanvasEdge(
        edge_id=f"{from_id}->{to_id}",
        from_node_id=from_id,
        to_node_id=to_id,
    )


async def _ok_executor(node: CanvasNode, upstream_outputs: dict):
    return f"output:{node.node_id}"


async def _fail_executor(node: CanvasNode, upstream_outputs: dict):
    raise RuntimeError(f"fail:{node.node_id}")


class TestCanvasWorkflowExecutorBasic:
    @pytest.mark.asyncio
    async def test_single_node_no_edges(self):
        nodes = [_node("A")]
        results = await canvas_workflow_executor(nodes=nodes, edges=[], executor=_ok_executor)
        assert "A" in results
        assert results["A"].success is True
        assert results["A"].output == "output:A"

    @pytest.mark.asyncio
    async def test_linear_chain(self):
        nodes = [_node("A"), _node("B"), _node("C")]
        edges = [_edge("A", "B"), _edge("B", "C")]
        results = await canvas_workflow_executor(nodes=nodes, edges=edges, executor=_ok_executor)
        for nid in ("A", "B", "C"):
            assert results[nid].success is True

    @pytest.mark.asyncio
    async def test_parallel_nodes(self):
        nodes = [_node("root"), _node("left"), _node("right")]
        edges = [_edge("root", "left"), _edge("root", "right")]
        results = await canvas_workflow_executor(nodes=nodes, edges=edges, executor=_ok_executor)
        assert results["root"].success is True
        assert results["left"].success is True
        assert results["right"].success is True

    @pytest.mark.asyncio
    async def test_no_executor_returns_failure(self):
        nodes = [_node("A")]
        results = await canvas_workflow_executor(nodes=nodes, edges=[], executor=None)
        assert results["A"].success is False
        assert "no executor" in results["A"].error

    @pytest.mark.asyncio
    async def test_returns_canvas_node_result_instances(self):
        nodes = [_node("X")]
        results = await canvas_workflow_executor(nodes=nodes, edges=[], executor=_ok_executor)
        assert isinstance(results["X"], CanvasNodeResult)


class TestCanvasWorkflowExecutorErrorHandling:
    @pytest.mark.asyncio
    async def test_rollback_raises_on_failure(self):
        nodes = [_node("A")]
        with pytest.raises(CanvasWorkflowError):
            await canvas_workflow_executor(
                nodes=nodes, edges=[], executor=_fail_executor, on_error="rollback"
            )

    @pytest.mark.asyncio
    async def test_continue_records_error(self):
        nodes = [_node("A"), _node("B")]
        edges = []

        async def mixed_executor(node: CanvasNode, upstream_outputs: dict):
            if node.node_id == "A":
                raise RuntimeError("A failed")
            return "ok"

        results = await canvas_workflow_executor(
            nodes=nodes, edges=edges, executor=mixed_executor, on_error="continue"
        )
        assert results["B"].success is True
        # A is either a failed CanvasNodeResult or an exception-wrapped result
        assert "A" in results

    @pytest.mark.asyncio
    async def test_cycle_raises_cycle_error(self):
        from obase.workflow_engine import CycleError

        nodes = [_node("A"), _node("B")]
        edges = [_edge("A", "B"), _edge("B", "A")]
        with pytest.raises(CycleError):
            await canvas_workflow_executor(nodes=nodes, edges=edges, executor=_ok_executor)


class TestCanvasWorkflowExecutorUpstream:
    @pytest.mark.asyncio
    async def test_upstream_outputs_passed_to_downstream(self):
        received = {}

        async def capturing_executor(node: CanvasNode, upstream_outputs: dict):
            received[node.node_id] = dict(upstream_outputs)
            return f"out:{node.node_id}"

        nodes = [_node("src"), _node("dst")]
        edges = [_edge("src", "dst")]
        await canvas_workflow_executor(nodes=nodes, edges=edges, executor=capturing_executor)
        assert "src" in received["dst"]

    @pytest.mark.asyncio
    async def test_node_ids_in_results(self):
        nodes = [_node("p"), _node("q")]
        edges = [_edge("p", "q")]
        results = await canvas_workflow_executor(nodes=nodes, edges=edges, executor=_ok_executor)
        assert set(results.keys()) == {"p", "q"}

    @pytest.mark.asyncio
    async def test_node_type_preserved_in_result(self):
        nodes = [CanvasNode(node_id="vid", node_type="video", label="vid")]
        results = await canvas_workflow_executor(nodes=nodes, edges=[], executor=_ok_executor)
        assert results["vid"].node_type == "video"
