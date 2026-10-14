"""Agent 画布操作桥 —— 操作注册表（单元 C：只读 + 写 + 付费 propose 闸）。

复用 BeefTV（MIT）的「op 描述符 / 权限模式 / CAS / 幂等 / 付费 propose」契约，
按 hevi 的 Python(FastAPI) 栈 reimplement（不 vendor 其 Go 代码）。
设计依据：``/data/soffy/projects/hevi-beeftv/BEEFTV_EVAL.md`` §4 单元 C。

每个操作描述符携带：
  - ``readOnly``      : bool  —— 只读操作不进写路径
  - ``scope``         : "canvas" | "asset" | "task" | "global"
  - ``params``        : JSON Schema（入参校验）
  - ``replay``        : "safe" | "unsafe"  —— 幂等重放是否安全（写操作均为 unsafe，需 opId 去重）

写操作（``readOnly=False``）一律要求：
  - ``expectedRevision`` (CAS)：与画布当前 revision 不一致 → 409，不修改。
  - ``opId``            (幂等)：同 opId+同参数重放 → 返回首次回执 ``replayed: true``；
                          同 opId 不同参数 → 拒绝（409/422）。

``canvas.generation.propose`` 是「只读但特殊」：只返回 ``proposalId``，
不创建任何生成任务、不调用任何 provider（付费闸）。确认后由既有任务接口提交。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4


@dataclass(frozen=True)
class OperationDescriptor:
    """一个 Agent 可执行的操作面描述符。"""

    name: str
    read_only: bool
    scope: str  # canvas | asset | task | global
    params: dict[str, Any]  # JSON Schema
    replay: str  # safe | unsafe
    summary: str = ""
    # 执行器：在 operation_bridge 里按 name 分派，这里只存元数据。
    handler: Callable[..., Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "readOnly": self.read_only,
            "scope": self.scope,
            "params": self.params,
            "replay": self.replay,
            "summary": self.summary,
        }


# ── 8 个首批描述符 ────────────────────────────────────────────────────────────
# 入参 schema 不重复 ShotSpec 的逐字段校验；合法取值由既有
# ``hevi.production.shot_spec.ShotSpec`` 校验器把关（见 operation_bridge）。

_ROW_SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "单行 ShotSpec（沿用既有 pydantic 校验器，未知 template/transition/sfx 等被拒）",
    "properties": {
        "template": {"type": "string"},
        "transition_in": {"type": "string"},
        "effect": {"type": "string"},
        "style": {"type": "string"},
        "sfx": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "offset": {"type": "number"}},
                "required": ["id"],
            },
        },
        "camera": {"type": "string"},
        "subtitle_style": {"type": "string"},
        "duration": {"type": "number"},
    },
    "additionalProperties": False,
}


def _descriptors() -> list[OperationDescriptor]:
    return [
        OperationDescriptor(
            name="canvas.get",
            read_only=True,
            scope="canvas",
            replay="safe",
            summary="读取画布图（节点/边/当前 revision）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string", "description": "画布图 UUID"},
                },
                "required": ["graph_id"],
            },
        ),
        OperationDescriptor(
            name="canvas.script.rows.append",
            read_only=False,
            scope="canvas",
            replay="unsafe",
            summary="在 ShotSpec 分镜表末尾追加一行（CAS + 幂等）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string"},
                    "row": _ROW_SPEC_SCHEMA,
                },
                "required": ["graph_id", "row"],
            },
        ),
        OperationDescriptor(
            name="canvas.script.rows.update",
            read_only=False,
            scope="canvas",
            replay="unsafe",
            summary="更新 ShotSpec 分镜表指定行（CAS + 幂等）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string"},
                    "row_index": {"type": "integer", "minimum": 0},
                    "row": _ROW_SPEC_SCHEMA,
                },
                "required": ["graph_id", "row_index", "row"],
            },
        ),
        OperationDescriptor(
            name="canvas.script.rows.remove",
            read_only=False,
            scope="canvas",
            replay="unsafe",
            summary="删除 ShotSpec 分镜表指定行（CAS + 幂等）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string"},
                    "row_index": {"type": "integer", "minimum": 0},
                },
                "required": ["graph_id", "row_index"],
            },
        ),
        OperationDescriptor(
            name="canvas.node.bind_asset",
            read_only=False,
            scope="canvas",
            replay="unsafe",
            summary="把资产（asset_id）绑定到画布节点（CAS + 幂等）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string"},
                    "node_id": {"type": "string"},
                    "asset_id": {"type": "string"},
                },
                "required": ["graph_id", "node_id", "asset_id"],
            },
        ),
        OperationDescriptor(
            name="canvas.generation.propose",
            read_only=True,
            scope="canvas",
            replay="safe",
            summary="付费闸：只生成 proposalId，不建任务、不调 provider（确认后由既有任务接口提交）",
            params={
                "type": "object",
                "properties": {
                    "graph_id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "rows": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "拟生成的分镜行号（仅记录意图，不触发生成）",
                    },
                },
                "required": ["graph_id"],
            },
        ),
        OperationDescriptor(
            name="asset.list",
            read_only=True,
            scope="asset",
            replay="safe",
            summary="列出可复用资产库条目（分类/版本）",
            params={
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
            },
        ),
        OperationDescriptor(
            name="task.get",
            read_only=True,
            scope="task",
            replay="safe",
            summary="读取既有生成任务状态/产物（任务表只读，不触发生成）",
            params={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                },
                "required": ["task_id"],
            },
        ),
    ]


_REGISTRY: dict[str, OperationDescriptor] = {d.name: d for d in _descriptors()}


def list_operations() -> list[OperationDescriptor]:
    """返回全部操作描述符（顺序稳定）。"""
    return list(_REGISTRY.values())


def get_operation(name: str) -> OperationDescriptor | None:
    return _REGISTRY.get(name)


def get_operation_names() -> list[str]:
    return list(_REGISTRY)


# ── 幂等回执缓存（同 opId 重放）──────────────────────────────────────────────
# 进程内存；key = (opId,) 存首次回执 + 归一化参数指纹。只用于「重放返回首次回执」。
_IDEMPOTENCY: dict[str, dict[str, Any]] = {}


def _fingerprint(params: dict[str, Any]) -> str:
    """对入参做稳定序列化指纹，用于『同 opId 不同参数应拒绝』。

    ``expectedRevision`` 是 CAS 并发控制字段，不计入幂等指纹——同一逻辑操作重放
    时 revision 已推进，若计入会让合法重放被误判为 conflict。
    """
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in params.items() if k != "expectedRevision"},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def record_receipt(op_id: str, params: dict[str, Any], receipt: dict[str, Any]) -> None:
    """记录首次回执，供重放时原样返回。"""
    _IDEMPOTENCY[op_id] = {"fp": _fingerprint(params), "receipt": receipt}


def lookup_receipt(op_id: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """查找重放回执：

    - 同 opId 且同参数 → 返回 ``{"receipt": <首次回执>, "replayed": True}``
    - 同 opId 但不同参数 → 返回 ``{"conflict": True}``
    - 无记录 → 返回 None
    """
    prev = _IDEMPOTENCY.get(op_id)
    if prev is None:
        return None
    if prev["fp"] != _fingerprint(params):
        return {"conflict": True}
    return {"receipt": prev["receipt"], "replayed": True}


def clear_idempotency() -> None:
    """测试用：清空幂等回执缓存。"""
    _IDEMPOTENCY.clear()


__all__ = [
    "OperationDescriptor",
    "list_operations",
    "get_operation",
    "get_operation_names",
    "record_receipt",
    "lookup_receipt",
    "clear_idempotency",
]
