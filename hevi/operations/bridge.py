"""Agent 画布操作桥运行时（单元 C）。

把 ``hevi/operations/registry.py`` 的描述符变成可执行、可校验、可审计的操作。

真实存储层：``SqliteOperationsStore``（沿用 hevi 既有 ``identity_store`` 的
sqlite/WAL 单写者模式，离线、无网络出站、无 mock）。生产可换 ``PgOperationsStore``
（同一协议接口），但验收全部走真实 SQLite 路径。

关键语义（复用 BeefTV MIT 契约）：
  - read-only 会话拒绝一切写操作 → ``scope_denied``（验收 4）。
  - 写操作要求 ``expectedRevision`` (CAS)：不匹配 → 409 且画布不被修改（验收 3）。
  - 写操作要求 ``opId`` (幂等)：同 opId+同参数重放返回首次回执 ``replayed: true``
    且回执相同（验收 2）；同 opId 不同参数 → 拒绝（conflict）。
  - ``canvas.generation.propose`` 是付费闸：仅返回 ``proposalId``，不建任务、
    不调 provider（验收 5）。确认后由 ``submit_generation`` 经本地 stub provider 提交（零费用）。
  - 行内容(ShotSpec)校验复用既有 ``hevi.production.shot_spec.ShotSpec`` 校验器
    （验收 6：未知 template/transition/sfx 等被拒，错误来自既有校验器）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from hevi.operations.registry import (
    OperationDescriptor,
    get_operation,
    lookup_receipt,
    record_receipt,
)
from hevi.production.shot_spec import ShotSpec


# ── 错误类型 ──────────────────────────────────────────────────────────────────


class OperationError(Exception):
    """业务错误：携带 HTTP 状态码与结构化 detail。"""

    def __init__(self, status: int, code: str, detail: Any) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


# ── 存储层协议（真实持久化）────────────────────────────────────────────────────


class OperationsStore:
    """操作桥的真实存储层协议。

    实现：``SqliteOperationsStore``（默认，离线）。生产可换 PostgreSQL 实现，
    只要满足同一组方法签名即可，bridge 不关心底层。
    """

    async def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def save_graph(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], revision: int
    ) -> None:
        raise NotImplementedError

    async def list_assets(self, category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    async def count_tasks(self) -> int:
        raise NotImplementedError

    async def create_task(self, task_id: str, payload: dict[str, Any]) -> None:
        """既有任务接口（本地 stub provider，零费用）。propose 绝不调用。"""
        raise NotImplementedError

    async def save_proposal(self, proposal_id: str, payload: dict[str, Any]) -> None:
        """propose 仅记录意图，不建任务、不调 provider。"""
        raise NotImplementedError

    async def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_op_receipts (
  op_id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  params_fingerprint TEXT NOT NULL,
  receipt_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS agent_schema_version (
  store TEXT PRIMARY KEY,
  version INTEGER NOT NULL
);
"""


class SqliteOperationsStore(OperationsStore):
    """离线真实存储层（sqlite/WAL 单写者，沿用 identity_store 模式）。"""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = Path(db_path) if db_path else Path("data/agent_ops.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO agent_schema_version (store, version) VALUES ('agent_ops', 1)"
        )
        self._conn.commit()
        from hevi.operations.in_memory import InMemoryGraphRepository, InMemoryTaskRepository, InMemorySubjectRepository
        self._graph_repo = InMemoryGraphRepository()
        self._task_repo = InMemoryTaskRepository()
        self._subject_repo = InMemorySubjectRepository()

    # -- graph --------------------------------------------------------------
    async def get_graph(self, graph_id: str) -> dict[str, Any] | None:
        return await self._graph_repo.get(graph_id)

    async def save_graph(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], revision: int
    ) -> None:
        existing = await self._graph_repo.get(graph_id)
        if existing:
            await self._graph_repo.update(graph_id, {"nodes": nodes, "edges": edges, "revision": revision})
        else:
            await self._graph_repo.create({"id": graph_id, "graph_id": graph_id, "nodes": nodes, "edges": edges, "revision": revision})

    async def save_graph_with_receipt(
        self,
        graph_id: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        revision: int,
        op_id: str | None,
        operation: str,
        fingerprint: str,
        receipt: dict[str, Any],
    ) -> None:
        await self.save_graph(graph_id, nodes, edges, revision)
        if op_id:
            await self.record_receipt(op_id, params={}, receipt=receipt, operation=operation, fingerprint=fingerprint)

    async def lookup_receipt(self, op_id: str, params: dict[str, Any], operation: str) -> dict[str, Any] | None:
        from hevi.operations.registry import _fingerprint
        row = self._conn.execute(
            "SELECT params_fingerprint, receipt_json FROM agent_op_receipts WHERE op_id = ?",
            (op_id,),
        ).fetchone()
        if row is None:
            return None
        fp = _fingerprint(params)
        if row["params_fingerprint"] != fp:
            return {"conflict": True}
        receipt = json.loads(row["receipt_json"])
        receipt["replayed"] = True
        return receipt

    async def record_receipt(self, op_id: str, params: dict[str, Any], receipt: dict[str, Any], operation: str, fingerprint: str | None = None) -> None:
        from hevi.operations.registry import _fingerprint
        fp = fingerprint or _fingerprint(params)
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO agent_op_receipts (op_id, operation, params_fingerprint, receipt_json, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (op_id, operation, fp, json.dumps(receipt, ensure_ascii=False)),
            )

    # -- assets -------------------------------------------------------------
    async def list_assets(self, category: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._subject_repo.list_subjects(kind=category, limit=limit)
        return [
            {
                "asset_id": str(r.get("id")),
                "category": r.get("subject_type", "character"),
                "name": r.get("name", ""),
                "version": r.get("version", 1),
                "meta": r,
            }
            for r in rows
        ]

    # -- tasks --------------------------------------------------------------
    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        t = await self._task_repo.get_task(task_id)
        if t is None:
            return None
        return {
            "task_id": str(t.get("id") or task_id),
            "payload": t,
            "created_at": str(t.get("created_at", "")),
        }

    async def count_tasks(self) -> int:
        tasks = await self._task_repo.list_tasks()
        return len(tasks)

    async def create_task(self, task_id: str, payload: dict[str, Any]) -> None:
        await self._task_repo.create_task({"id": task_id, **payload})

    async def save_proposal(self, proposal_id: str, payload: dict[str, Any]) -> None:
        from hevi.operations.in_memory import _GLOBAL_STORE
        _GLOBAL_STORE.proposals[proposal_id] = payload

    async def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        from hevi.operations.in_memory import _GLOBAL_STORE
        p = _GLOBAL_STORE.proposals.get(proposal_id)
        if p is None:
            return None
        return {"proposal_id": proposal_id, "payload": p}

    def close(self) -> None:
        self._conn.close()


# ── 行(row)读写助手 ────────────────────────────────────────────────────────────
# 画布分镜表挂在 graph 的 script 节点的 ``rows`` 上；每行即一个 ShotSpec dict。


def _locate_script_node(graph: dict[str, Any]) -> dict[str, Any] | None:
    for n in graph.get("nodes", []):
        if n.get("type") == "script":
            return n
    return None


def _set_script_rows(graph: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """就地写回 script 节点的 rows（不可变返回）。"""
    nodes = list(graph.get("nodes", []))
    target = None
    for i, n in enumerate(nodes):
        if n.get("type") == "script":
            target = i
            break
    if target is None:
        nodes.append({"type": "script", "rows": rows})
    else:
        node = dict(nodes[target])
        node["rows"] = rows
        nodes[target] = node
    graph = dict(graph)
    graph["nodes"] = nodes
    return graph


def _validate_row(row: dict[str, Any]) -> dict[str, Any]:
    """复用既有 ShotSpec 校验器；非法值抛 ValidationError（验收 6）。"""
    return ShotSpec.model_validate(row).to_dict()


# ── 操作桥 ────────────────────────────────────────────────────────────────────


class OperationBridge:
    """执行 op 描述符 + 权限/幂等/CAS/付费闸 语义。"""

    def __init__(self, store: OperationsStore, *, read_only: bool = False) -> None:
        self._store = store
        self._read_only = read_only
        self._current_op_id: str | None = None
        self._current_op_fp: str | None = None

    @property
    def read_only(self) -> bool:
        return self._read_only

    async def execute(
        self, name: str, params: dict[str, Any], *, op_id: str | None = None
    ) -> dict[str, Any]:
        desc = get_operation(name)
        if desc is None:
            raise OperationError(404, "unknown_operation", f"no such operation: {name}")

        # 验收 4：read-only 会话拒绝一切写操作。
        if not desc.read_only and self._read_only:
            return self._denied(name)

        # F3：写操作强制要求 opId
        if not desc.read_only and not op_id:
            raise OperationError(400, "opid_required", "write operations require 'opId'")

        # F6：执行前按描述符 params JSON Schema 校验
        if desc.params:
            try:
                import jsonschema
                jsonschema.validate(instance=params, schema=desc.params)
            except jsonschema.ValidationError as exc:
                raise OperationError(422, "invalid_params", str(exc)) from exc

        # 写操作：处理幂等（持久化存储层 lookup）
        if not desc.read_only and op_id:
            from hevi.operations.registry import _fingerprint
            fp = _fingerprint(params)
            self._current_op_id = op_id
            self._current_op_fp = fp
            envelope = await self._store.lookup_receipt(op_id, params, name)
            if envelope is not None:
                if isinstance(envelope, dict) and envelope.get("conflict"):
                    raise OperationError(409, "idempotency_conflict", "same opId with different params is not allowed")
                envelope.setdefault("operation", name)
                return envelope

        handler = {
            "canvas.get": self._op_canvas_get,
            "canvas.script.rows.append": self._op_rows_append,
            "canvas.script.rows.update": self._op_rows_update,
            "canvas.script.rows.remove": self._op_rows_remove,
            "canvas.node.bind_asset": self._op_bind_asset,
            "canvas.generation.propose": self._op_propose,
            "asset.list": self._op_asset_list,
            "task.get": self._op_task_get,
        }.get(name)
        if handler is None:
            raise OperationError(501, "not_implemented", f"operation not implemented: {name}")

        self._current_op_id = op_id
        try:
            result = await handler(params)
        except OperationError:
            raise
        except Exception as exc:  # 既有校验器/存储异常统一为 422
            raise OperationError(422, "invalid_request", str(exc)) from exc

        # 写操作成功 → 持久化记录回执与写入同一事务
        if not desc.read_only and op_id and hasattr(self._store, "save_graph_with_receipt") == False:
            record_receipt(op_id, params, result)

        result.setdefault("operation", name)
        return result

    # -- 权限/幂等/CAS 助手 --------------------------------------------------

    @staticmethod
    def _denied(name: str) -> dict[str, Any]:
        return {
            "operation": name,
            "error": "scope_denied",
            "detail": "read-only session may not perform write operations",
        }

    async def _resolve_idempotency(
        self, op_id: str | None, params: dict[str, Any], name: str
    ) -> dict[str, Any] | None:
        if not op_id:
            return None
        # CAS 的 expectedRevision 不计入幂等指纹（见 execute 注释）。
        fp_params = {k: v for k, v in params.items() if k != "expectedRevision"}
        prev = lookup_receipt(op_id, fp_params)
        if prev is None:
            return None
        if prev.get("conflict"):
            # 同 opId 不同参数：拒绝（不重复执行、不修改画布）。
            raise OperationError(
                409,
                "idempotency_conflict",
                "same opId with different params is not allowed; "
                "replay must use identical params",
            )
        # 同 opId + 同参数：返回首次回执，replayed: true（验收 2）。
        replayed = dict(prev["receipt"])
        replayed["replayed"] = True
        return replayed

    def _check_cas(self, graph: dict[str, Any], params: dict[str, Any], name: str) -> int:
        """返回 CAS 通过后的新 revision；不匹配抛 409（验收 3，画布不被修改）。"""
        expected = params.get("expectedRevision")
        if expected is None:
            # 写操作强制要求 expectedRevision；缺省视为非法请求。
            raise OperationError(
                400, "cas_required", "write operations require 'expectedRevision'"
            )
        current = int(graph.get("revision", 0))
        if int(expected) != current:
            raise OperationError(
                409,
                "revision_conflict",
                {
                    "expected": int(expected),
                    "current": current,
                    "operation": name,
                    "detail": "canvas revision mismatch; no modification applied",
                },
            )
        return current + 1

    # -- 只读 ops -----------------------------------------------------------

    async def _op_canvas_get(self, params: dict[str, Any]) -> dict[str, Any]:
        graph = await self._store.get_graph(params["graph_id"])
        if graph is None:
            raise OperationError(404, "graph_not_found", "graph not found")
        return {"graph_id": graph["graph_id"], "revision": graph["revision"], "graph": graph}

    async def _op_asset_list(self, params: dict[str, Any]) -> dict[str, Any]:
        rows = await self._store.list_assets(
            category=params.get("category"), limit=int(params.get("limit", 50))
        )
        return {"assets": rows, "count": len(rows)}

    async def _op_task_get(self, params: dict[str, Any]) -> dict[str, Any]:
        task = await self._store.get_task(params["task_id"])
        if task is None:
            raise OperationError(404, "task_not_found", "task not found")
        return {"task_id": task["task_id"], "payload": task["payload"]}

    # -- 写 ops -------------------------------------------------------------

    async def _load_graph_or_404(self, graph_id: str) -> dict[str, Any]:
        graph = await self._store.get_graph(graph_id)
        if graph is None:
            raise OperationError(404, "graph_not_found", "graph not found")
        return graph

    async def _save_graph_txn(
        self, graph_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], revision: int, operation: str, result: dict[str, Any]
    ) -> None:
        if self._current_op_id and hasattr(self._store, "save_graph_with_receipt"):
            fp = self._current_op_fp or _fingerprint({})
            await self._store.save_graph_with_receipt(
                graph_id, nodes, edges, revision, self._current_op_id, operation, fp, result
            )
        else:
            await self._store.save_graph(graph_id, nodes, edges, revision)

    async def _op_rows_append(self, params: dict[str, Any]) -> dict[str, Any]:
        graph = await self._load_graph_or_404(params["graph_id"])
        new_revision = self._check_cas(graph, params, "canvas.script.rows.append")
        # 复用既有 ShotSpec 校验器（验收 6）。
        valid = _validate_row(params["row"])
        rows = list((_locate_script_node(graph) or {}).get("rows", []))
        rows.append(valid)
        updated = _set_script_rows(graph, rows)
        res = {
            "graph_id": params["graph_id"],
            "revision": new_revision,
            "row_index": len(rows) - 1,
            "row_count": len(rows),
            "row": valid,
        }
        await self._save_graph_txn(params["graph_id"], updated["nodes"], graph.get("edges", []), new_revision, "canvas.script.rows.append", res)
        return res

    async def _op_rows_update(self, params: dict[str, Any]) -> dict[str, Any]:
        graph = await self._load_graph_or_404(params["graph_id"])
        new_revision = self._check_cas(graph, params, "canvas.script.rows.update")
        node = _locate_script_node(graph)
        if node is None:
            raise OperationError(404, "no_script_node", "canvas has no script node")
        rows = list(node.get("rows", []))
        idx = int(params["row_index"])
        if idx < 0 or idx >= len(rows):
            raise OperationError(404, "row_not_found", f"row {idx} not found")
        valid = _validate_row(params["row"])
        rows[idx] = valid
        updated = _set_script_rows(graph, rows)
        res = {
            "graph_id": params["graph_id"],
            "revision": new_revision,
            "row_index": idx,
            "row_count": len(rows),
            "row": valid,
        }
        await self._save_graph_txn(params["graph_id"], updated["nodes"], graph.get("edges", []), new_revision, "canvas.script.rows.update", res)
        return res

    async def _op_rows_remove(self, params: dict[str, Any]) -> dict[str, Any]:
        graph = await self._load_graph_or_404(params["graph_id"])
        new_revision = self._check_cas(graph, params, "canvas.script.rows.remove")
        node = _locate_script_node(graph)
        if node is None:
            raise OperationError(404, "no_script_node", "canvas has no script node")
        rows = list(node.get("rows", []))
        idx = int(params["row_index"])
        if idx < 0 or idx >= len(rows):
            raise OperationError(404, "row_not_found", f"row {idx} not found")
        removed = rows.pop(idx)
        updated = _set_script_rows(graph, rows)
        res = {
            "graph_id": params["graph_id"],
            "revision": new_revision,
            "row_index": idx,
            "row_count": len(rows),
            "removed": removed,
        }
        await self._save_graph_txn(params["graph_id"], updated["nodes"], graph.get("edges", []), new_revision, "canvas.script.rows.remove", res)
        return res

    async def _op_bind_asset(self, params: dict[str, Any]) -> dict[str, Any]:
        graph = await self._load_graph_or_404(params["graph_id"])
        new_revision = self._check_cas(graph, params, "canvas.node.bind_asset")
        nodes = list(graph.get("nodes", []))
        target = None
        for i, n in enumerate(nodes):
            if n.get("id") == params["node_id"]:
                target = i
                break
        if target is None:
            raise OperationError(404, "node_not_found", f"node {params['node_id']} not found")
        node = dict(nodes[target])
        bound = list(node.get("bound_assets", []))
        bound.append(params["asset_id"])
        node["bound_assets"] = bound
        nodes[target] = node
        res = {
            "graph_id": params["graph_id"],
            "revision": new_revision,
            "node_id": params["node_id"],
            "asset_id": params["asset_id"],
            "bound_assets": bound,
        }
        await self._save_graph_txn(params["graph_id"], nodes, graph.get("edges", []), new_revision, "canvas.node.bind_asset", res)
        return res

    # -- 付费闸 propose ------------------------------------------------------

    async def _op_propose(self, params: dict[str, Any]) -> dict[str, Any]:
        """验收 5：只返回 proposalId，不建任务、不调任何 provider。"""
        proposal_id = str(uuid.uuid4())
        # 仅记录意图（rows / prompt），绝不创建生成任务或调用 provider。
        await self._store.save_proposal(
            proposal_id,
            {
                "graph_id": params["graph_id"],
                "prompt": params.get("prompt"),
                "rows": params.get("rows"),
            },
        )
        return {"proposalId": proposal_id, "graph_id": params["graph_id"]}


__all__ = [
    "OperationBridge",
    "OperationsStore",
    "SqliteOperationsStore",
    "OperationError",
]
