"""Execution-time node graph store (canvas MVP).

Two implementations of the same small contract:

* ``PgNodeStore`` — Postgres tables created by ``c4a11ab1e002``; used by the
  API/executor in production.
* ``InMemoryNodeStore`` — the same semantics in dicts, for unit tests and for
  offline demos without a database.

``canvas_graphs.nodes_json`` / ``edges_json`` remain the compatibility mirror;
the node graph is the execution source of truth.  An edit marks the changed
node and its downstream ``stale`` without touching their content or revision.
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from obase.persistence import PgPool, insert_one, query

from hevi.canvas import graph_diff as gd

_KIND_BY_SUFFIX = {
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
    ".wav": "audio",
    ".mp3": "audio",
    ".m4a": "audio",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".srt": "text",
    ".txt": "text",
    ".md": "text",
    ".json": "text",
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


def _digest_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def normalize_artifacts(output: Any) -> list[dict[str, Any]]:
    """Turn an executor output into artifact rows (path/kind/digest/mime).

    Explicit ``artifacts`` entries win; otherwise a plain ``output`` path or
    the common mp4/png/wav keys are picked up.  Non-path outputs produce no
    artifact (the node's JSON output is still persisted).
    """
    out = output if isinstance(output, dict) else {}
    candidates: list[dict[str, Any]] = []
    explicit = out.get("artifacts")
    explicit_found = False
    if isinstance(explicit, list):
        for item in explicit:
            if isinstance(item, dict) and item.get("path"):
                candidates.append(dict(item))
                explicit_found = True
            elif isinstance(item, str):
                candidates.append({"path": item})
                explicit_found = True
    if not explicit_found:
        # Only infer paths when the executor did not declare artifacts;
        # otherwise inherited context keys (e.g. an upstream audio path) would
        # be recorded as this node's output.
        for key in ("output", "mp4", "video", "audio", "image", "path", "subtitle", "fcpxml"):
            value = out.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append({"path": value})
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        path_str = str(item.get("path")).strip()
        if not path_str or path_str in seen:
            continue
        seen.add(path_str)
        path = Path(path_str)
        suffix = path.suffix.lower()
        kind = str(item.get("kind") or _KIND_BY_SUFFIX.get(suffix) or "file")
        result.append(
            {
                "kind": kind,
                "path": path_str,
                "mime": item.get("mime") or mimetypes.guess_type(path_str)[0],
                "digest": item.get("digest") or _digest_file(path),
                "size_bytes": item.get("size_bytes")
                if item.get("size_bytes") is not None
                else (path.stat().st_size if path.is_file() else None),
                "storage_key": item.get("storage_key"),
                "meta": item.get("meta") or {},
            }
        )
    return result


@dataclass
class NodeState:
    node_key: str
    node_type: str
    config: dict[str, Any] = field(default_factory=dict)
    label: str = ""
    position: dict[str, Any] = field(default_factory=dict)
    input_refs: list[Any] = field(default_factory=list)
    status: str = gd.STATUS_PENDING
    revision: int = 0
    locked: bool = False
    review: dict[str, Any] | None = None
    output: Any = None
    artifact_id: str | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    estimated_cost: float = 0.0
    actual_cost: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "node_id": self.node_key,
            "node_type": self.node_type,
            "config": self.config,
            "label": self.label,
            "position": self.position,
            "input_refs": self.input_refs,
            "status": self.status,
            "revision": self.revision,
            "locked": self.locked,
            "review": self.review,
            "output": self.output,
            "artifact_id": self.artifact_id,
            "artifacts": self.artifacts,
            "estimated_cost": self.estimated_cost,
            "actual_cost": self.actual_cost,
        }

    def brief(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "revision": self.revision,
            "locked": self.locked,
            "review": self.review,
        }


class NodeStore(Protocol):
    async def load_nodes(self, graph_id: str) -> dict[str, NodeState]: ...

    async def load_edges(self, graph_id: str) -> list[dict[str, Any]]: ...

    async def sync_graph(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any]: ...

    async def mark_stale(self, graph_id: str, node_keys: list[str]) -> list[str]: ...

    async def set_status(
        self,
        graph_id: str,
        node_key: str,
        status: str,
        *,
        review: dict[str, Any] | None = None,
    ) -> NodeState | None: ...

    async def save_result(
        self,
        graph_id: str,
        node_key: str,
        *,
        status: str,
        output: Any,
        review: dict[str, Any] | None,
        estimated_cost: float = 0.0,
        actual_cost: float = 0.0,
        pricing_key: str | None = None,
    ) -> NodeState | None: ...

    async def set_locked(self, graph_id: str, node_key: str, locked: bool) -> NodeState | None: ...

    async def get_node(self, graph_id: str, node_key: str) -> NodeState | None: ...


# ── In-memory implementation ─────────────────────────────────────────────────


class InMemoryNodeStore:
    """Dict-backed store with the same stale/revision semantics as Postgres."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, NodeState]] = {}
        self._edges: dict[str, list[dict[str, Any]]] = {}
        self._revisions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._synced: set[str] = set()

    def _bucket(self, graph_id: str) -> dict[str, NodeState]:
        return self._nodes.setdefault(str(graph_id), {})

    async def load_nodes(self, graph_id: str) -> dict[str, NodeState]:
        return {k: NodeState(**vars(v)) for k, v in self._bucket(graph_id).items()}

    async def load_edges(self, graph_id: str) -> list[dict[str, Any]]:
        return [dict(e) for e in self._edges.get(str(graph_id), [])]

    async def sync_graph(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any]:
        gid = str(graph_id)
        bucket = self._bucket(gid)
        old_nodes = [self._node_json(n) for n in bucket.values()]
        incoming = {str(gd._node_key(n)): n for n in nodes if gd._node_key(n)}
        changed = gd.affected_nodes(old_nodes, nodes, edges)
        for key, node in incoming.items():
            state = bucket.get(key)
            if state is None:
                state = NodeState(
                    node_key=key,
                    node_type=str(node.get("node_type") or "text"),
                    label=str(node.get("label") or key),
                    position=dict(node.get("position") or {}),
                    config=dict(node.get("config") or {}),
                    input_refs=list(node.get("input_refs") or []),
                )
                bucket[key] = state
            else:
                if gd.node_fingerprint(self._node_json(state)) != gd.node_fingerprint(node):
                    if not state.locked:
                        state.status = gd.STATUS_STALE
                    state.config = dict(node.get("config") or {})
                state.node_type = str(node.get("node_type") or state.node_type)
                state.label = str(node.get("label") or state.label)
                state.position = dict(node.get("position") or state.position)
        for key in list(bucket):
            if key not in incoming:
                del bucket[key]
        for key in changed:
            state = bucket.get(key)
            if state is not None and not state.locked and state.status not in (
                gd.STATUS_PENDING,
                gd.STATUS_RUNNING,
            ):
                state.status = gd.STATUS_STALE
        self._edges[gid] = [
            {
                "edge_key": str(e.get("edge_id") or e.get("id") or f"{e.get('from_node_id')}->{e.get('to_node_id')}"),
                "from_node_id": str(e.get("from_node_id") or e.get("source") or ""),
                "to_node_id": str(e.get("to_node_id") or e.get("target") or ""),
                "kind": str(e.get("kind") or "data"),
                "meta": dict(e.get("meta") or {}),
            }
            for e in edges
        ]
        self._synced.add(gid)
        return {"stale": sorted(changed), "graph_id": gid, "nodes": len(bucket)}

    @staticmethod
    def _node_json(state: NodeState) -> dict[str, Any]:
        return {
            "node_id": state.node_key,
            "node_type": state.node_type,
            "config": state.config,
            "input_refs": state.input_refs,
        }

    async def mark_stale(self, graph_id: str, node_keys: list[str]) -> list[str]:
        marked: list[str] = []
        bucket = self._bucket(graph_id)
        for key in node_keys:
            state = bucket.get(key)
            if state is not None and not state.locked:
                state.status = gd.STATUS_STALE
                marked.append(key)
        return marked

    async def set_status(
        self,
        graph_id: str,
        node_key: str,
        status: str,
        *,
        review: dict[str, Any] | None = None,
    ) -> NodeState | None:
        state = self._bucket(graph_id).get(node_key)
        if state is None:
            return None
        state.status = status
        if review is not None:
            state.review = review
        return state

    async def save_result(
        self,
        graph_id: str,
        node_key: str,
        *,
        status: str,
        output: Any,
        review: dict[str, Any] | None,
        estimated_cost: float = 0.0,
        actual_cost: float = 0.0,
        pricing_key: str | None = None,
    ) -> NodeState | None:
        state = self._bucket(graph_id).get(node_key)
        if state is None:
            return None
        revision = state.revision + 1
        artifacts = normalize_artifacts(output)
        if artifacts:
            state.artifact_id = str(uuid.uuid4())
        state.status = status
        state.revision = revision
        state.output = _jsonable(output)
        state.review = _jsonable(review)
        state.artifacts = artifacts
        state.estimated_cost = float(estimated_cost)
        state.actual_cost = float(actual_cost)
        self._revisions.setdefault((str(graph_id), node_key), []).append(
            {
                "revision": revision,
                "config_snapshot": _jsonable(state.config),
                "artifact_id": state.artifact_id,
                "review_result": state.review,
                "output": state.output,
                "pricing_key": pricing_key,
            }
        )
        return state

    async def set_locked(self, graph_id: str, node_key: str, locked: bool) -> NodeState | None:
        state = self._bucket(graph_id).get(node_key)
        if state is None:
            return None
        state.locked = bool(locked)
        if locked:
            state.status = gd.STATUS_LOCKED
        return state

    async def get_node(self, graph_id: str, node_key: str) -> NodeState | None:
        return self._bucket(graph_id).get(node_key)

    async def list_revisions(self, graph_id: str, node_key: str) -> list[dict[str, Any]]:
        return list(self._revisions.get((str(graph_id), node_key), []))


# ── Postgres implementation ──────────────────────────────────────────────────


class PgNodeStore:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def _write(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        """Run an UPDATE/DELETE ... RETURNING without the SELECT helper's LIMIT."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    async def load_nodes(self, graph_id: str) -> dict[str, NodeState]:
        rows = await query(
            self._pool,
            sql=(
                "SELECT * FROM canvas_nodes WHERE graph_id = $1 "
                "AND deleted_at IS NULL ORDER BY created_at"
            ),
            params=[uuid.UUID(graph_id)],
            limit=1000,
        )
        states: dict[str, NodeState] = {}
        for row in rows:
            state = self._state_from_row(row)
            states[state.node_key] = state
        if states:
            arts = await query(
                self._pool,
                sql=(
                    "SELECT * FROM canvas_artifacts WHERE graph_id = $1 "
                    "ORDER BY created_at DESC"
                ),
                params=[uuid.UUID(graph_id)],
                limit=2000,
            )
            by_node: dict[str, list[dict[str, Any]]] = {}
            for art in arts:
                by_node.setdefault(str(art["node_id"]), []).append(_artifact_row(art))
            for row in rows:
                state = states[str(row["node_key"])]
                state.artifacts = by_node.get(str(row["id"]), [])
        return states

    async def load_edges(self, graph_id: str) -> list[dict[str, Any]]:
        rows = await query(
            self._pool,
            sql=(
                "SELECT e.*, fn.node_key AS from_key, tn.node_key AS to_key "
                "FROM canvas_edges e "
                "JOIN canvas_nodes fn ON fn.id = e.from_node_id "
                "JOIN canvas_nodes tn ON tn.id = e.to_node_id "
                "WHERE e.graph_id = $1"
            ),
            params=[uuid.UUID(graph_id)],
            limit=2000,
        )
        return [
            {
                "edge_key": str(r["edge_key"]),
                "from_node_id": str(r["from_key"]),
                "to_node_id": str(r["to_key"]),
                "kind": str(r["kind"]),
                "meta": r.get("meta") or {},
            }
            for r in rows
        ]

    async def sync_graph(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any]:
        gid = uuid.UUID(graph_id)
        existing = await self.load_nodes(graph_id)
        old_nodes = [
            {
                "node_id": s.node_key,
                "node_type": s.node_type,
                "config": s.config,
                "input_refs": s.input_refs,
            }
            for s in existing.values()
        ]
        incoming = {str(gd._node_key(n)): n for n in nodes if gd._node_key(n)}
        changed = gd.affected_nodes(old_nodes, nodes, edges)
        now = _utcnow()

        for key, node in incoming.items():
            state = existing.get(key)
            node_type = str(node.get("node_type") or "text")
            config = _jsonable(node.get("config") or {})
            position = _jsonable(node.get("position") or {})
            label = str(node.get("label") or key)
            input_refs = _jsonable(node.get("input_refs") or [])
            if state is None:
                await insert_one(
                    self._pool,
                    table="canvas_nodes",
                    data={
                        "id": uuid.uuid4(),
                        "graph_id": gid,
                        "node_key": key,
                        "node_type": node_type,
                        "label": label,
                        "config": config,
                        "position": position,
                        "input_refs": input_refs,
                        "status": gd.STATUS_PENDING,
                        "revision": 0,
                        "locked": False,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                continue
            self_changed = gd.node_fingerprint(
                {
                    "node_id": state.node_key,
                    "node_type": state.node_type,
                    "config": state.config,
                    "input_refs": state.input_refs,
                }
            ) != gd.node_fingerprint(node)
            await self._write(
                "UPDATE canvas_nodes SET node_type=$2, label=$3, config=$4, "
                "position=$5, input_refs=$6, updated_at=$7, "
                "status = CASE WHEN $8 THEN 'stale' ELSE status END "
                "WHERE graph_id=$1 AND node_key=$9 AND locked = false",
                [gid, node_type, label, config, position, input_refs, now, self_changed, key],
            )

        # Mark every affected node stale (the edited node itself and all its
        # downstream). Content/revision are not touched.
        if changed:
            await self._write(
                "UPDATE canvas_nodes SET status='stale', updated_at=$3 "
                "WHERE graph_id=$1 AND node_key = ANY($2::text[]) AND locked=false "
                "AND status NOT IN ('pending','running')",
                [gid, sorted(changed), now],
            )

        # Soft-delete nodes removed from the JSON mirror.
        removed = [k for k in existing if k not in incoming]
        for key in removed:
            await self._write(
                "UPDATE canvas_nodes SET deleted_at=$3, updated_at=$3 "
                "WHERE graph_id=$1 AND node_key=$2",
                [gid, key, now],
            )

        # Rebuild edges (small graphs; deterministic and idempotent).
        await self._write("DELETE FROM canvas_edges WHERE graph_id=$1", [gid])
        key_to_id = {
            row["node_key"]: row["id"]
            for row in await query(
                self._pool,
                sql="SELECT id, node_key FROM canvas_nodes WHERE graph_id=$1 AND deleted_at IS NULL",
                params=[gid],
                limit=1000,
            )
        }
        for edge in edges:
            src = str(edge.get("from_node_id") or edge.get("source") or "")
            dst = str(edge.get("to_node_id") or edge.get("target") or "")
            if src not in key_to_id or dst not in key_to_id:
                continue
            await insert_one(
                self._pool,
                table="canvas_edges",
                data={
                    "id": uuid.uuid4(),
                    "graph_id": gid,
                    "edge_key": str(
                        edge.get("edge_id")
                        or edge.get("id")
                        or f"{src}->{dst}"
                    ),
                    "from_node_id": key_to_id[src],
                    "to_node_id": key_to_id[dst],
                    "kind": str(edge.get("kind") or "data"),
                    "meta": _jsonable(edge.get("meta") or {}),
                    "created_at": now,
                },
            )

        await self._write(
            "UPDATE canvas_graphs SET graph_revision = graph_revision + 1, "
            "materialized_at = $2, updated_at = $2 WHERE id = $1",
            [gid, now],
        )
        return {"stale": sorted(changed), "graph_id": str(gid), "nodes": len(incoming)}

    async def mark_stale(self, graph_id: str, node_keys: list[str]) -> list[str]:
        if not node_keys:
            return []
        rows = await self._write(
            "UPDATE canvas_nodes SET status='stale', updated_at=$3 "
            "WHERE graph_id=$1 AND node_key = ANY($2::text[]) AND locked=false "
            "RETURNING node_key",
            [uuid.UUID(graph_id), node_keys, _utcnow()],
        )
        return [str(r["node_key"]) for r in rows]

    async def set_status(
        self,
        graph_id: str,
        node_key: str,
        status: str,
        *,
        review: dict[str, Any] | None = None,
    ) -> NodeState | None:
        values: dict[str, Any] = {"status": status, "updated_at": _utcnow()}
        if review is not None:
            values["review"] = _jsonable(review)
        await self._write(
            "UPDATE canvas_nodes SET status=$3, review=COALESCE($4, review), "
            "updated_at=$5 WHERE graph_id=$1 AND node_key=$2",
            [uuid.UUID(graph_id), node_key, status, values.get("review"), values["updated_at"]],
        )
        return await self.get_node(graph_id, node_key)

    async def save_result(
        self,
        graph_id: str,
        node_key: str,
        *,
        status: str,
        output: Any,
        review: dict[str, Any] | None,
        estimated_cost: float = 0.0,
        actual_cost: float = 0.0,
        pricing_key: str | None = None,
    ) -> NodeState | None:
        state = await self.get_node(graph_id, node_key)
        if state is None:
            return None
        gid = uuid.UUID(graph_id)
        now = _utcnow()
        node_id = await self._node_uuid(graph_id, node_key)
        if node_id is None:
            return None
        artifacts = normalize_artifacts(output)
        artifact_id: uuid.UUID | None = None
        for art in artifacts:
            artifact_id = uuid.uuid4()
            await insert_one(
                self._pool,
                table="canvas_artifacts",
                data={
                    "id": artifact_id,
                    "graph_id": gid,
                    "node_id": node_id,
                    "kind": art["kind"],
                    "path": art["path"],
                    "storage_key": art.get("storage_key"),
                    "digest": art.get("digest"),
                    "mime": art.get("mime"),
                    "size_bytes": art.get("size_bytes"),
                    "meta": _jsonable(art.get("meta") or {}),
                    "created_at": now,
                },
            )
        revision = state.revision + 1
        payload = _jsonable(output)
        review_payload = _jsonable(review)
        prompt = ""
        if isinstance(state.config, dict):
            prompt = str(state.config.get("prompt") or state.config.get("content") or "")
        if isinstance(output, dict):
            prompt = str(output.get("prompt") or prompt)
        await insert_one(
            self._pool,
            table="canvas_node_revisions",
            data={
                "id": uuid.uuid4(),
                "node_id": node_id,
                "revision": revision,
                "config_snapshot": _jsonable(state.config),
                "prompt": prompt,
                "artifact_id": artifact_id,
                "review_result": review_payload,
                "output": payload,
                "created_at": now,
            },
        )
        await insert_one(
            self._pool,
            table="canvas_node_costs",
            data={
                "id": uuid.uuid4(),
                "node_id": node_id,
                "revision": revision,
                "estimate": float(estimated_cost),
                "actual": float(actual_cost),
                "currency": "USD",
                "pricing_key": pricing_key,
                "created_at": now,
            },
        )
        await self._write(
            "UPDATE canvas_nodes SET status=$3, revision=$4, artifact_id=$5, "
            "review=$6, output=$7, estimated_cost=$8, actual_cost=$9, updated_at=$10 "
            "WHERE graph_id=$1 AND node_key=$2",
            [gid, node_key, status, revision, artifact_id, review_payload, payload,
             float(estimated_cost), float(actual_cost), now],
        )
        return await self.get_node(graph_id, node_key)

    async def set_locked(self, graph_id: str, node_key: str, locked: bool) -> NodeState | None:
        await self._write(
            "UPDATE canvas_nodes SET locked=$3, "
            "status=CASE WHEN $3 THEN 'locked' WHEN status='locked' THEN 'pending' ELSE status END, "
            "updated_at=$4 WHERE graph_id=$1 AND node_key=$2",
            [uuid.UUID(graph_id), node_key, bool(locked), _utcnow()],
        )
        return await self.get_node(graph_id, node_key)

    async def get_node(self, graph_id: str, node_key: str) -> NodeState | None:
        rows = await query(
            self._pool,
            sql=(
                "SELECT * FROM canvas_nodes WHERE graph_id=$1 AND node_key=$2 "
                "AND deleted_at IS NULL"
            ),
            params=[uuid.UUID(graph_id), node_key],
            limit=1,
        )
        if not rows:
            return None
        state = self._state_from_row(rows[0])
        arts = await query(
            self._pool,
            sql=(
                "SELECT * FROM canvas_artifacts WHERE node_id=$1 ORDER BY created_at DESC"
            ),
            params=[rows[0]["id"]],
            limit=200,
        )
        state.artifacts = [_artifact_row(a) for a in arts]
        return state

    async def list_revisions(self, graph_id: str, node_key: str) -> list[dict[str, Any]]:
        node_id = await self._node_uuid(graph_id, node_key)
        if node_id is None:
            return []
        return await query(
            self._pool,
            sql=(
                "SELECT revision, config_snapshot, artifact_id, review_result, output, created_at "
                "FROM canvas_node_revisions WHERE node_id=$1 ORDER BY revision DESC"
            ),
            params=[node_id],
            limit=200,
        )

    async def _node_uuid(self, graph_id: str, node_key: str) -> uuid.UUID | None:
        rows = await query(
            self._pool,
            sql=(
                "SELECT id FROM canvas_nodes WHERE graph_id=$1 AND node_key=$2 "
                "AND deleted_at IS NULL"
            ),
            params=[uuid.UUID(graph_id), node_key],
            limit=1,
        )
        return rows[0]["id"] if rows else None

    @staticmethod
    def _state_from_row(row: dict[str, Any]) -> NodeState:
        return NodeState(
            node_key=str(row["node_key"]),
            node_type=str(row["node_type"]),
            config=row.get("config") or {},
            label=str(row.get("label") or ""),
            position=row.get("position") or {},
            input_refs=row.get("input_refs") or [],
            status=str(row.get("status") or gd.STATUS_PENDING),
            revision=int(row.get("revision") or 0),
            locked=bool(row.get("locked")),
            review=row.get("review"),
            output=row.get("output"),
            artifact_id=str(row["artifact_id"]) if row.get("artifact_id") else None,
            estimated_cost=float(row.get("estimated_cost") or 0),
            actual_cost=float(row.get("actual_cost") or 0),
        )


def _artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "kind": str(row.get("kind") or "file"),
        "path": str(row.get("path") or ""),
        "storage_key": row.get("storage_key"),
        "digest": row.get("digest"),
        "mime": row.get("mime"),
        "size_bytes": row.get("size_bytes"),
        "meta": row.get("meta") or {},
        "created_at": str(row.get("created_at") or ""),
    }
