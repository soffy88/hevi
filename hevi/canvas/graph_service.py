from __future__ import annotations

import uuid
from typing import Any

from hevi.canvas.graph_repository import GraphRepository


class GraphService:
    """画布图持久化业务层 — save/load/list/update/delete canvas graphs."""

    def __init__(self, repo: GraphRepository) -> None:
        self._repo = repo

    async def save_graph(
        self,
        *,
        name: str = "Untitled",
        description: str = "",
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        user_id: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "name": name,
            "description": description,
            "nodes_json": nodes,
            "edges_json": edges,
            "user_id": user_id,
        }
        return await self._repo.create(data)

    async def load_graph(self, graph_id: str) -> dict[str, Any] | None:
        return await self._repo.get(graph_id)

    async def list_graphs(
        self, *, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        return await self._repo.list_graphs(user_id=user_id)

    async def update_graph(
        self,
        graph_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        nodes: list[dict[str, Any]] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if nodes is not None:
            updates["nodes_json"] = nodes
        if edges is not None:
            updates["edges_json"] = edges
        if not updates:
            return await self._repo.get(graph_id)
        return await self._repo.update(graph_id, updates)

    async def delete_graph(self, graph_id: str) -> bool:
        return await self._repo.delete(graph_id)
