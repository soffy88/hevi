"""Canvas edge-matrix cure tests (2026-10-25).

Single source of truth: hevi/canvas/validation.py EDGE_MATRIX.
These tests prove, not merely assert by construction:

1. The two cured edges (script -> audio, video -> text) are legal.
2. The frontend matrix (hevi-web/src/lib/canvas-rules.ts) is exactly
   equal to the backend matrix -- any future front/back divergence
   fails here, by parsing the real TS file rather than a copy.
3. oprim's matrix is NOT authoritative: where it disagrees with hevi
   (script -> audio, video -> text), hevi wins and validation passes.
4. The full canonical 7-type workflow chain runs end to end through
   ExecutorService with stub executors (zero real generation cost):
   script -> first_frame -> tail_frame -> video -> audio ->
   subtitle -> assemble, mapped by workflow_adapter to canvas types.

All fixtures are invented for this file only; no generation, network,
or real provider call is made (the node executor is a stub, and the
real canvas_workflow_executor only orchestrates it).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oprim.hevi_types import CanvasEdge, CanvasNode

from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.canvas.validation import (
    EDGE_COMPATIBLE,
    EDGE_MATRIX,
    GraphValidationError,
    edge_compatible,
    validate_graph,
)
from hevi.canvas.workflow_adapter import canvas_edge_warnings, workflow_to_graph
from hevi.capabilities.canvas_workflow import create_workflow


def _dag():
    # Canonical 7-type chain (same shape as the adapter tests):
    # script -> first_frame -> video -> subtitle -> assemble,
    # script -> audio -> assemble, script -> tail_frame -> video.
    return create_workflow(
        [
            {"node_id": "w_script", "type": "script",
             "params": {"title": "invented title"}},
            {"node_id": "w_frame", "type": "first_frame",
             "inputs": ["w_script"], "params": {"prompt": "invented frame"}},
            {"node_id": "w_tail", "type": "tail_frame",
             "inputs": ["w_script"], "params": {"prompt": "invented tail"}},
            {"node_id": "w_video", "type": "video",
             "inputs": ["w_frame", "w_tail"],
             "params": {"duration_s": 5}},
            {"node_id": "w_audio", "type": "audio",
             "inputs": ["w_script"], "params": {"voice": "invented"}},
            {"node_id": "w_sub", "type": "subtitle",
             "inputs": ["w_video"], "params": {"language": "en"}},
            {"node_id": "w_asm", "type": "assemble",
             "inputs": ["w_video", "w_audio", "w_sub"]},
        ]
    )


def _nodes_edges(graph):
    nodes = [CanvasNode.model_validate(n) for n in graph["nodes"]]
    edges = [CanvasEdge.model_validate(e) for e in graph["edges"]]
    return nodes, edges


def _frontend_matrix() -> dict[str, set[str]]:
    """Parse EDGE_MATRIX out of the real frontend file (no copy)."""
    ts_path = Path(__file__).resolve().parents[1] / "hevi-web" / "src" / "lib" / "canvas-rules.ts"
    text = ts_path.read_text(encoding="utf-8")
    block = re.search(
        r"const EDGE_MATRIX[^=]*=\s*\{(.*?)\n\};", text, re.DOTALL
    )
    assert block is not None, "EDGE_MATRIX block not found in canvas-rules.ts"
    matrix: dict[str, set[str]] = {}
    for match in re.finditer(r"^\s*(\w+):\s*\[([^\]]*)\]", block.group(1), re.MULTILINE):
        matrix[match.group(1)] = set(re.findall(r"'(\w+)'", match.group(2)))
    return matrix


# ── 1. The two cured edges ──────────────────────────────────────────────────

def test_cured_edges_are_legal():
    assert edge_compatible(from_type="script", to_type="audio") is True
    assert edge_compatible(from_type="video", to_type="text") is True


def test_matrix_is_exactly_fourteen_edges():
    # 14 cured-matrix edges + 2 material-pack edges (segment ->
    # segment continuation, asset -> segment reference) = 16.
    assert len(EDGE_COMPATIBLE) == 16
    assert EDGE_COMPATIBLE == {
        ("text", "image"), ("text", "video"), ("text", "audio"), ("text", "script"),
        ("image", "video"), ("image", "image"), ("image", "script"),
        ("video", "video"), ("video", "audio"), ("video", "text"),
        ("audio", "video"),
        ("script", "image"), ("script", "video"), ("script", "audio"),
        ("segment", "segment"),
        ("asset", "segment"),
    }


def test_previously_legal_edges_stay_legal_and_illegal_stay_illegal():
    # Retained from the prior matrices: dropping either would break a
    # previously legal graph, so the cure is a union, not a rewrite.
    assert edge_compatible(from_type="image", to_type="script") is True
    assert edge_compatible(from_type="video", to_type="audio") is True
    # Still illegal: no silent legalisation beyond the cure.
    for pair in [("audio", "text"), ("text", "text"), ("audio", "audio"),
                 ("script", "script"), ("image", "audio"), ("image", "text"),
                 ("segment", "video"), ("segment", "text"), ("video", "segment"),
                 ("asset", "asset"), ("asset", "text"), ("asset", "video"),
                 ("segment", "asset")]:
        assert edge_compatible(from_type=pair[0], to_type=pair[1]) is False


def test_matrix_and_pair_set_agree():
    rebuilt = {
        (src, dst) for src, targets in EDGE_MATRIX.items() for dst in targets
    }
    assert rebuilt == EDGE_COMPATIBLE
    assert set(EDGE_MATRIX) == {
        "text", "image", "video", "audio", "script", "segment", "asset",
    }


# ── 2. Front/back consistency (parsed, not copied) ───────────────────────────

def test_frontend_matrix_equals_backend_matrix():
    frontend = _frontend_matrix()
    backend = {src: set(targets) for src, targets in EDGE_MATRIX.items()}
    assert frontend == backend


def test_frontend_matrix_contains_cured_edges():
    frontend = _frontend_matrix()
    assert "audio" in frontend["script"]
    assert "text" in frontend["video"]


# ── 3. oprim is reference-only; hevi wins on disagreement ────────────────────

def test_hevi_overrides_oprim_where_they_disagree():
    from oprim.canvas_edge_validate import canvas_edge_validate

    # oprim still lacks both cured edges -- and that no longer matters:
    # hevi validation does not consult it, so these graphs validate.
    assert canvas_edge_validate(from_type="script", to_type="audio") is False
    assert canvas_edge_validate(from_type="video", to_type="text") is False
    nodes = [CanvasNode(node_id="s", node_type="script"),
             CanvasNode(node_id="a", node_type="audio")]
    edges = [CanvasEdge(edge_id="e", from_node_id="s", to_node_id="a",
                        from_type="script", to_type="audio")]
    validate_graph(nodes, edges)  # must not raise


def test_validate_graph_still_rejects_genuinely_illegal_edge():
    nodes = [CanvasNode(node_id="a", node_type="audio"),
             CanvasNode(node_id="t", node_type="text")]
    edges = [CanvasEdge(edge_id="e", from_node_id="a", to_node_id="t",
                        from_type="audio", to_type="text")]
    with pytest.raises(GraphValidationError, match="Invalid edges"):
        validate_graph(nodes, edges)


# ── 4. Canonical 7-type chain: validation + adapter + execution ─────────────

def test_canonical_seven_type_graph_validates_and_has_no_warnings():
    graph = workflow_to_graph(_dag())
    assert len(graph["nodes"]) == 7
    assert len(graph["edges"]) == 9
    nodes, edges = _nodes_edges(graph)
    validate_graph(nodes, edges)  # must not raise
    assert canvas_edge_warnings(graph) == []


def test_canonical_seven_type_mapped_edges_are_the_cured_ones():
    graph = workflow_to_graph(_dag())
    pairs = {(e["from_type"], e["to_type"]) for e in graph["edges"]}
    assert ("script", "audio") in pairs
    assert ("video", "text") in pairs
    assert pairs <= EDGE_COMPATIBLE


@pytest.mark.asyncio
async def test_executor_service_runs_full_seven_type_chain_with_stubs():
    """ExecutorService end to end with stub node executors.

    The real canvas_workflow_executor orchestrates; the stub replaces
    only the per-node executor, so no real generation, provider, or
    network call happens. Previously this raised GraphValidationError
    on script -> audio / video -> text before any node ran.
    """
    graph = workflow_to_graph(_dag())
    stored: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": "Invented 7-type chain",
        "description": "",
        "nodes_json": graph["nodes"],
        "edges_json": graph["edges"],
        "user_id": None,
    }
    graph_id = stored["id"]
    repo = GraphRepository(MagicMock())
    svc = GraphService(repo)
    exe = ExecutorService(svc)

    async def stub_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
        return {"type": node.node_type, "stub": node.node_id,
                "upstream": sorted(upstream)}

    with (
        patch.object(svc, "load_graph", new_callable=AsyncMock, return_value=stored),
        patch(
            "hevi.canvas.executor_service.create_node_executor",
            return_value=stub_executor,
        ),
    ):
        result = await exe.execute_graph(graph_id)

    assert result["graph_id"] == graph_id
    assert result["status"] == "completed"
    assert result["node_count"] == 7
    assert set(result["results"]) == {
        "w_script", "w_frame", "w_tail", "w_video",
        "w_audio", "w_sub", "w_asm",
    }
    assert all(r["success"] for r in result["results"].values())
    assert result["preflight"]["estimated_cost_usd"] == 0.0
