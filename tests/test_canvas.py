"""P11.D tests — canvas graph CRUD, validation, node_mapper, executor, API routes."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from oprim._hevi_types import CanvasEdge, CanvasNode

from hevi.canvas.executor_service import ExecutorService
from hevi.canvas.graph_repository import GraphRepository
from hevi.canvas.graph_service import GraphService
from hevi.canvas.node_mapper import (
    NODE_EXECUTORS,
    VALID_NODE_TYPES,
    create_node_executor,
)
from hevi.canvas.validation import (
    GraphValidationError,
    check_orphans,
    detect_cycle,
    validate_edges,
    validate_graph,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_GID = str(uuid.uuid4())
_STORED: dict[str, Any] = {
    "id": _GID,
    "name": "Test Graph",
    "description": "",
    "nodes_json": [
        {"node_id": "n1", "node_type": "text", "label": "T", "config": {}, "position": {}},
        {"node_id": "n2", "node_type": "image", "label": "I", "config": {}, "position": {}},
    ],
    "edges_json": [
        {
            "edge_id": "e1",
            "from_node_id": "n1",
            "to_node_id": "n2",
            "from_type": "text",
            "to_type": "image",
        }
    ],
    "user_id": None,
}


def _make_repo() -> tuple[GraphRepository, MagicMock]:
    pool = MagicMock()
    return GraphRepository(pool), pool


def _make_svc() -> GraphService:
    repo, _ = _make_repo()
    return GraphService(repo)


def _make_node(node_id: str, node_type: str) -> CanvasNode:
    return CanvasNode(node_id=node_id, node_type=node_type)


def _make_edge(
    edge_id: str, from_id: str, to_id: str, from_type: str = "", to_type: str = ""
) -> CanvasEdge:
    return CanvasEdge(
        edge_id=edge_id,
        from_node_id=from_id,
        to_node_id=to_id,
        from_type=from_type,
        to_type=to_type,
    )


# ── 1. GraphService — save / load / list ──────────────────────────────────────


@pytest.mark.asyncio
async def test_save_graph_calls_insert() -> None:
    repo, _ = _make_repo()
    _target = "hevi.canvas.graph_repository.insert_one"
    with (
        patch(_target, new_callable=AsyncMock, return_value=uuid.UUID(_GID)) as m,
        patch(
            "hevi.canvas.graph_repository.read_one",
            new_callable=AsyncMock,
            return_value=_STORED,
        ),
    ):
        svc = GraphService(repo)
        result = await svc.save_graph(
            name="Test Graph", nodes=_STORED["nodes_json"], edges=_STORED["edges_json"]
        )
    assert result["name"] == "Test Graph"
    m.assert_awaited_once()
    assert m.call_args.kwargs["table"] == "canvas_graphs"


@pytest.mark.asyncio
async def test_load_graph_returns_none_for_missing() -> None:
    repo, _ = _make_repo()
    missing_id = str(uuid.uuid4())
    with patch("hevi.canvas.graph_repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = GraphService(repo)
        result = await svc.load_graph(missing_id)
    assert result is None


@pytest.mark.asyncio
async def test_load_graph_returns_record() -> None:
    repo, _ = _make_repo()
    _t = "hevi.canvas.graph_repository.read_one"
    with patch(_t, new_callable=AsyncMock, return_value=_STORED):
        svc = GraphService(repo)
        result = await svc.load_graph(_GID)
    assert result is not None
    assert result["id"] == _GID


@pytest.mark.asyncio
async def test_list_graphs() -> None:
    repo, _ = _make_repo()
    _qt = "hevi.canvas.graph_repository.query"
    with patch(_qt, new_callable=AsyncMock, return_value=[_STORED]) as m:
        svc = GraphService(repo)
        results = await svc.list_graphs()
    assert len(results) == 1
    assert "canvas_graphs" in m.call_args.kwargs["sql"]


@pytest.mark.asyncio
async def test_update_graph() -> None:
    repo, _ = _make_repo()
    updated = {**_STORED, "name": "Renamed"}
    # repo.update() calls read_one twice: once for existence, once for post-update fetch
    with (
        patch(
            "hevi.canvas.graph_repository.read_one",
            new_callable=AsyncMock,
            side_effect=[_STORED, updated],
        ),
        patch("hevi.canvas.graph_repository.update_one", new_callable=AsyncMock, return_value=True),
    ):
        svc = GraphService(repo)
        result = await svc.update_graph(_GID, name="Renamed")
    assert result is not None
    assert result["name"] == "Renamed"


@pytest.mark.asyncio
async def test_delete_graph_returns_true() -> None:
    repo, _ = _make_repo()
    with (
        patch(
            "hevi.canvas.graph_repository.read_one", new_callable=AsyncMock, return_value=_STORED
        ),
        patch("hevi.canvas.graph_repository.update_one", new_callable=AsyncMock, return_value=True),
    ):
        svc = GraphService(repo)
        result = await svc.delete_graph(_GID)
    assert result is True


@pytest.mark.asyncio
async def test_delete_graph_missing_returns_false() -> None:
    repo, _ = _make_repo()
    missing = str(uuid.uuid4())
    with patch("hevi.canvas.graph_repository.read_one", new_callable=AsyncMock, return_value=None):
        svc = GraphService(repo)
        result = await svc.delete_graph(missing)
    assert result is False


# ── 2. Graph JSON serialization ───────────────────────────────────────────────


def test_canvas_node_json_roundtrip() -> None:
    node = CanvasNode(node_id="n1", node_type="image", config={"sub_type": "three_view"})
    data = node.model_dump()
    restored = CanvasNode.model_validate(data)
    assert restored.node_id == "n1"
    assert restored.config["sub_type"] == "three_view"


def test_canvas_edge_json_roundtrip() -> None:
    edge = CanvasEdge(
        edge_id="e1", from_node_id="n1", to_node_id="n2", from_type="text", to_type="image"
    )
    data = edge.model_dump()
    restored = CanvasEdge.model_validate(data)
    assert restored.edge_id == "e1"
    assert restored.from_type == "text"


# ── 3. Validation — edges ─────────────────────────────────────────────────────


def test_validate_edges_compatible() -> None:
    nodes = [_make_node("n1", "text"), _make_node("n2", "image")]
    edges = [_make_edge("e1", "n1", "n2", from_type="text", to_type="image")]
    errors = validate_edges(nodes, edges)
    assert errors == []


def test_validate_edges_incompatible() -> None:
    nodes = [_make_node("n1", "audio"), _make_node("n2", "text")]
    edges = [_make_edge("e1", "n1", "n2", from_type="audio", to_type="text")]
    errors = validate_edges(nodes, edges)
    assert len(errors) == 1
    assert "audio" in errors[0]
    assert "text" in errors[0]


def test_validate_edges_uses_node_type_when_edge_types_empty() -> None:
    nodes = [_make_node("n1", "text"), _make_node("n2", "video")]
    # from_type/to_type are empty → should fall back to node_type
    edges = [_make_edge("e1", "n1", "n2")]
    errors = validate_edges(nodes, edges)
    assert errors == []  # text → video is compatible


# ── 4. Validation — cycle detection ──────────────────────────────────────────


def test_detect_cycle_raises_on_cycle() -> None:
    from obase.workflow_engine import CycleError

    nodes = [_make_node("n1", "text"), _make_node("n2", "image")]
    edges = [
        _make_edge("e1", "n1", "n2"),
        _make_edge("e2", "n2", "n1"),  # cycle
    ]
    with pytest.raises(CycleError):
        detect_cycle(nodes, edges)


def test_detect_cycle_passes_on_dag() -> None:
    nodes = [_make_node("n1", "text"), _make_node("n2", "image"), _make_node("n3", "video")]
    edges = [_make_edge("e1", "n1", "n2"), _make_edge("e2", "n2", "n3")]
    detect_cycle(nodes, edges)  # no exception


# ── 5. Validation — orphan detection ─────────────────────────────────────────


def test_check_orphans_finds_isolated_node() -> None:
    nodes = [_make_node("n1", "text"), _make_node("n2", "image"), _make_node("n3", "video")]
    edges = [_make_edge("e1", "n1", "n2")]  # n3 has no connections
    orphans = check_orphans(nodes, edges)
    assert "n3" in orphans


def test_check_orphans_single_node_not_orphan() -> None:
    nodes = [_make_node("n1", "text")]
    edges: list[CanvasEdge] = []
    orphans = check_orphans(nodes, edges)
    assert orphans == []


def test_validate_graph_empty_raises() -> None:
    with pytest.raises(GraphValidationError, match="at least one node"):
        validate_graph([], [])


def test_validate_graph_invalid_edge_raises() -> None:
    nodes = [_make_node("n1", "audio"), _make_node("n2", "text")]
    edges = [_make_edge("e1", "n1", "n2", from_type="audio", to_type="text")]
    with pytest.raises(GraphValidationError, match="Invalid edges"):
        validate_graph(nodes, edges)


# ── 6. node_mapper — 5 types + registry ──────────────────────────────────────


def test_node_executors_registry_has_5_types() -> None:
    assert set(NODE_EXECUTORS.keys()) == {"text", "image", "video", "audio", "script"}


def test_valid_node_types_has_5() -> None:
    assert VALID_NODE_TYPES == frozenset({"text", "image", "video", "audio", "script"})


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", ["text", "image", "video", "audio", "script"])
async def test_node_executor_dispatches_all_types(node_type: str) -> None:
    executor = create_node_executor()
    node = _make_node("n1", node_type)
    result = await executor(node, {})
    assert isinstance(result, dict)
    assert result["type"] == node_type


@pytest.mark.asyncio
async def test_node_executor_unknown_type_raises() -> None:
    executor = create_node_executor()
    node = _make_node("n1", "unknown_type")
    with pytest.raises(ValueError, match="Unknown node type"):
        await executor(node, {})


@pytest.mark.asyncio
async def test_node_executor_text_includes_upstream_count() -> None:
    executor = create_node_executor()
    node = CanvasNode(node_id="n1", node_type="text", config={"content": "hello"})
    upstream = {"prev": "some_output"}
    result = await executor(node, upstream)
    assert result["output"] == "hello"
    assert result["upstream_count"] == 1


# ── 7. ExecutorService — execute_graph ───────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_graph_calls_canvas_workflow_executor() -> None:
    from oprim.canvas_node_execute import CanvasNodeResult

    graph_svc = _make_svc()
    exe = ExecutorService(graph_svc)

    node_result = CanvasNodeResult(
        node_id="n1", output={"type": "text"}, node_type="text", success=True
    )
    with (
        patch.object(graph_svc, "load_graph", new_callable=AsyncMock, return_value=_STORED),
        patch(
            "hevi.canvas.executor_service.canvas_workflow_executor",
            new_callable=AsyncMock,
            return_value={"n1": node_result},
        ) as mock_exec,
    ):
        result = await exe.execute_graph(_GID)

    assert result["graph_id"] == _GID
    assert result["status"] == "completed"
    assert "n1" in result["results"]
    mock_exec.assert_awaited_once()
    # Verify hevi's executor was injected
    assert mock_exec.call_args.kwargs["executor"] is not None


@pytest.mark.asyncio
async def test_execute_graph_not_found_raises() -> None:
    graph_svc = _make_svc()
    exe = ExecutorService(graph_svc)
    with patch.object(graph_svc, "load_graph", new_callable=AsyncMock, return_value=None):
        with pytest.raises(ValueError, match="Graph not found"):
            await exe.execute_graph("missing-id")


@pytest.mark.asyncio
async def test_execute_graph_invalid_graph_rejected() -> None:
    graph_svc = _make_svc()
    exe = ExecutorService(graph_svc)

    bad_graph = {
        **_STORED,
        "nodes_json": [
            {"node_id": "n1", "node_type": "audio", "label": "", "config": {}, "position": {}},
            {"node_id": "n2", "node_type": "text", "label": "", "config": {}, "position": {}},
        ],
        "edges_json": [
            {
                "edge_id": "e1",
                "from_node_id": "n1",
                "to_node_id": "n2",
                "from_type": "audio",
                "to_type": "text",
            }
        ],
    }
    with patch.object(graph_svc, "load_graph", new_callable=AsyncMock, return_value=bad_graph):
        with pytest.raises(GraphValidationError, match="Invalid edges"):
            await exe.execute_graph(_GID)


@pytest.mark.asyncio
async def test_execute_graph_partial_status_on_node_failure() -> None:
    from oprim.canvas_node_execute import CanvasNodeResult

    graph_svc = _make_svc()
    exe = ExecutorService(graph_svc)

    failed_result = CanvasNodeResult(
        node_id="n1", output=None, node_type="text", success=False, error="no executor"
    )
    with (
        patch.object(graph_svc, "load_graph", new_callable=AsyncMock, return_value=_STORED),
        patch(
            "hevi.canvas.executor_service.canvas_workflow_executor",
            new_callable=AsyncMock,
            return_value={"n1": failed_result},
        ),
    ):
        result = await exe.execute_graph(_GID, on_error="continue")

    assert result["status"] == "partial"


# ── 8. API routes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_save_graph(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    svc = _make_svc()
    with patch.object(svc, "save_graph", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.post(
            "/api/canvas/graphs",
            json={"name": "Test Graph", "nodes": [], "edges": []},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "Test Graph"


@pytest.mark.asyncio
async def test_api_list_graphs(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    svc = _make_svc()
    with patch.object(svc, "list_graphs", new_callable=AsyncMock, return_value=[_STORED]):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.get("/api/canvas/graphs")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_api_get_graph(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    svc = _make_svc()
    with patch.object(svc, "load_graph", new_callable=AsyncMock, return_value=_STORED):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.get(f"/api/canvas/graphs/{_GID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == _GID


@pytest.mark.asyncio
async def test_api_get_graph_404(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    svc = _make_svc()
    with patch.object(svc, "load_graph", new_callable=AsyncMock, return_value=None):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.get("/api/canvas/graphs/nonexistent")
        app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_update_graph(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    updated = {**_STORED, "name": "Renamed"}
    svc = _make_svc()
    with patch.object(svc, "update_graph", new_callable=AsyncMock, return_value=updated):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.patch(
            f"/api/canvas/graphs/{_GID}",
            json={"name": "Renamed"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_api_delete_graph(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_graph_service

    svc = _make_svc()
    with patch.object(svc, "delete_graph", new_callable=AsyncMock, return_value=True):
        app.dependency_overrides[get_graph_service] = lambda: svc
        resp = await client.delete(f"/api/canvas/graphs/{_GID}")
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_api_execute_graph(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_executor_service

    exe_result = {
        "graph_id": _GID,
        "status": "completed",
        "node_count": 2,
        "results": {"n1": {"node_id": "n1", "success": True}},
    }
    svc = _make_svc()
    exe = ExecutorService(svc)
    with patch.object(exe, "execute_graph", new_callable=AsyncMock, return_value=exe_result):
        app.dependency_overrides[get_executor_service] = lambda: exe
        resp = await client.post(
            f"/api/canvas/graphs/{_GID}/execute",
            json={"on_error": "rollback"},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_api_execute_graph_not_found(client: Any) -> None:
    from hevi.api.main import app
    from hevi.api.routers.canvas import get_executor_service

    svc = _make_svc()
    exe = ExecutorService(svc)
    err = ValueError("Graph not found")
    with patch.object(exe, "execute_graph", new_callable=AsyncMock, side_effect=err):
        app.dependency_overrides[get_executor_service] = lambda: exe
        resp = await client.post(
            "/api/canvas/graphs/missing/execute",
            json={},
        )
        app.dependency_overrides.clear()
    assert resp.status_code == 404
