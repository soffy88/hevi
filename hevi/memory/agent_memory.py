"""Agent 记忆管理器——封装 embed + store + retrieve 的完整 API。

三级记忆:
- 短期(short_term): 当前会话的消息缓冲,不持久化
- 长期(long_term): 跨会话的摘要记忆,持久化到向量库
- 语义(semantic): 基于向量检索的相关记忆召回

典型用法:
    memory = AgentMemory(namespace="task-123")
    memory.remember("角色A在市集被刺杀", {"type": "event", "character": "角色A"})
    results = memory.recall("角色A的结局", top_k=3)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.memory.embedding import EmbeddingProvider, LocalHashEmbedding
from hevi.memory.vector_store import FileVectorStore, MemoryEntry, VectorStore

logger = logging.getLogger(__name__)


@dataclass
class AgentMemory:
    """Agent 记忆管理器。

    Args:
        namespace: 记忆隔离空间(通常 = task_id 或 session_id)
        embedding: 向量化 provider,默认 LocalHashEmbedding(128 维)
        store: 向量存储,默认 FileVectorStore
        max_short_term: 短期记忆缓冲上限(条),超出后自动 flush 到长期
    """

    namespace: str = "default"
    embedding: EmbeddingProvider = field(default_factory=lambda: LocalHashEmbedding())
    store: VectorStore | None = None
    max_short_term: int = 50
    _short_term: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = FileVectorStore(namespace=self.namespace)

    # ── 写入 ─────────────────────────────────────────────────────────────

    def remember(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        *,
        session_id: str = "",
    ) -> MemoryEntry:
        """存入一条长期记忆(立即持久化)。"""
        meta = metadata or {}
        meta.setdefault("memory_type", "long_term")
        embedding = self.embedding.embed(text)
        entry = MemoryEntry(
            id="",  # auto-generated in __post_init__
            text=text,
            embedding=embedding,
            metadata=meta,
            session_id=session_id,
        )
        self.store.add(entry)
        return entry

    def remember_batch(
        self,
        items: list[tuple[str, dict[str, Any]]],
        *,
        session_id: str = "",
    ) -> list[MemoryEntry]:
        """批量存入长期记忆。"""
        entries: list[MemoryEntry] = []
        for text, meta in items:
            meta.setdefault("memory_type", "long_term")
            embedding = self.embedding.embed(text)
            entries.append(
                MemoryEntry(
                    id="",
                    text=text,
                    embedding=embedding,
                    metadata=meta,
                    session_id=session_id,
                )
            )
        self.store.add_batch(entries)
        return entries

    def push_short_term(self, message: dict[str, Any]) -> None:
        """追加一条短期消息。超出 max_short_term 时自动 flush。"""
        self._short_term.append(message)
        if len(self._short_term) > self.max_short_term:
            self.flush_short_term()

    def flush_short_term(self) -> int:
        """将短期记忆批量转入长期记忆。返回转入条数。"""
        if not self._short_term:
            return 0
        items = [
            (
                msg.get("content", str(msg)),
                {**msg, "memory_type": "short_term_flushed"},
            )
            for msg in self._short_term
        ]
        self.remember_batch(items)
        count = len(self._short_term)
        self._short_term.clear()
        return count

    def summarize_session(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str = "",
        summary_prefix: str = "会话摘要: ",
    ) -> MemoryEntry:
        """将一组会话消息摘要后存入长期记忆。

        简单实现:拼接所有 content → 截断到 500 字。
        生产环境可替换为 LLM 摘要。
        """
        combined = " ".join(
            str(m.get("content", m)) for m in messages
        )
        summary = combined[:500] if len(combined) > 500 else combined
        return self.remember(
            f"{summary_prefix}{summary}",
            metadata={
                "memory_type": "session_summary",
                "message_count": len(messages),
                "summarized_at": datetime.now(tz=None).isoformat(),
            },
            session_id=session_id,
        )

    # ── 检索 ─────────────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        top_k: int = 5,
        **filters: Any,
    ) -> list[MemoryEntry]:
        """语义检索长期记忆。"""
        query_embedding = self.embedding.embed(query)
        return self.store.search(query_embedding, top_k=top_k, **filters)

    def get_short_term(self) -> list[dict[str, Any]]:
        """获取当前短期记忆缓冲(只读副本)。"""
        return list(self._short_term)

    # ── 统计 ─────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """记忆统计。"""
        return {
            "namespace": self.namespace,
            "long_term_count": self.store.count(),
            "short_term_count": len(self._short_term),
            "embedding_dim": self.embedding.dim,
        }

    def clear_all(self) -> None:
        """清空所有记忆(长期 + 短期)。"""
        self.store.clear()
        self._short_term.clear()
