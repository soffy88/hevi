"""Agent 记忆 API——手动写入/语义检索/统计。"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.memory import AgentMemory, FileVectorStore

router = APIRouter(prefix="/memory", tags=["memory"])

_memories: dict[str, AgentMemory] = {}


def _get_memory(namespace: str) -> AgentMemory:
    if namespace not in _memories:
        _memories[namespace] = AgentMemory(
            namespace=namespace,
            store=FileVectorStore(
                base_dir=Path("output/memory"),
                namespace=namespace,
            ),
        )
    return _memories[namespace]


# ── Request schemas ──────────────────────────────────────────────────────────


class RememberRequest(BaseModel):
    namespace: str = "default"
    text: str
    metadata: dict[str, Any] = {}
    session_id: str = ""


class RecallRequest(BaseModel):
    namespace: str = "default"
    query: str
    top_k: int = 5
    filters: dict[str, Any] = {}


class SummarizeRequest(BaseModel):
    namespace: str = "default"
    messages: list[dict[str, Any]] = []
    session_id: str = ""


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/remember")
async def remember(
    body: RememberRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """存入一条长期记忆。"""
    mem = _get_memory(body.namespace)
    entry = mem.remember(body.text, body.metadata, session_id=body.session_id)
    return {"status": "ok", "entry_id": entry.id}


@router.post("/recall")
async def recall(
    body: RecallRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """语义检索记忆。"""
    mem = _get_memory(body.namespace)
    results = mem.recall(body.query, top_k=body.top_k, **body.filters)
    return [
        {
            "id": e.id,
            "text": e.text,
            "metadata": e.metadata,
            "timestamp": e.timestamp,
            "session_id": e.session_id,
        }
        for e in results
    ]


@router.post("/summarize")
async def summarize_session(
    body: SummarizeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """将会话消息摘要后存入长期记忆。"""
    mem = _get_memory(body.namespace)
    entry = mem.summarize_session(body.messages, session_id=body.session_id)
    return {"status": "ok", "entry_id": entry.id}


@router.get("/{namespace}/stats")
async def memory_stats(
    namespace: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """记忆统计。"""
    mem = _get_memory(namespace)
    return mem.stats()


@router.delete("/{namespace}")
async def clear_memory(
    namespace: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, str]:
    """清空指定 namespace 的全部记忆。"""
    mem = _get_memory(namespace)
    mem.clear_all()
    return {"status": "cleared", "namespace": namespace}
