"""向量存储——JSON 文件 + cosine similarity 检索。

零依赖实现,适合 Hevi 单实例部署。多实例/大规模场景可替换为
pgvector / FAISS / Chroma 等,只要实现 VectorStore 协议。
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass
class MemoryEntry:
    """单条记忆记录。"""

    id: str
    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    session_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=None).isoformat()
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryEntry:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class VectorStore(Protocol):
    """向量存储协议。"""

    def add(self, entry: MemoryEntry) -> None: ...

    def add_batch(self, entries: list[MemoryEntry]) -> None: ...

    def search(self, query_embedding: list[float], top_k: int = 5, **filters: Any) -> list[MemoryEntry]: ...

    def delete(self, entry_id: str) -> bool: ...

    def count(self) -> int: ...

    def clear(self) -> None: ...


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """cosine similarity,处理零向量。"""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class FileVectorStore:
    """基于 JSON 文件的向量存储。

    线程安全(读写加锁),适合单进程部署。
    数据落盘到 `{base_dir}/{namespace}.json`,进程重启后自动加载。
    """

    def __init__(self, base_dir: Path | str = Path("output/memory"), namespace: str = "default") -> None:
        self._base_dir = Path(base_dir)
        self._namespace = namespace
        self._lock = threading.Lock()
        self._entries: list[MemoryEntry] = []
        self._path = self._base_dir / f"{self._namespace}.json"
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._entries = [MemoryEntry.from_dict(d) for d in data]
            except (json.JSONDecodeError, KeyError):
                self._entries = []
        else:
            self._entries = []

    def _save(self) -> None:
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([e.to_dict() for e in self._entries], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            self._save()

    def add_batch(self, entries: list[MemoryEntry]) -> None:
        with self._lock:
            self._entries.extend(entries)
            self._save()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        **filters: Any,
    ) -> list[MemoryEntry]:
        """cosine similarity 检索 + metadata 过滤。"""
        with self._lock:
            candidates = self._entries
            # metadata 过滤
            for key, value in filters.items():
                if value is not None:
                    candidates = [
                        e for e in candidates if e.metadata.get(key) == value
                    ]
            # 计算相似度并排序
            scored = [
                (e, _cosine_similarity(query_embedding, e.embedding))
                for e in candidates
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            return [e for e, _ in scored[:top_k]]

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            before = len(self._entries)
            self._entries = [e for e in self._entries if e.id != entry_id]
            changed = len(self._entries) < before
            if changed:
                self._save()
            return changed

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._save()

    @property
    def namespace(self) -> str:
        return self._namespace
