"""hevi.memory —— 跨会话 Agent 记忆(3O oskill 风格, 差距 A3)。

对标 Toonflow 的本地 ONNX 向量检索记忆(短记忆/长摘要/语义召回), 补 hevi 差距:
此前长文改编上下文靠 prompt 硬塞, 无跨会话记忆。

实现(零重依赖, 仅 stdlib sqlite3):
  - 三档记忆(对齐 Toonflow 分层):
      short_term  短记忆: 最近 N 条原始事件(如最近处理过的剧集/镜头决定)
      summary     长摘要: 按主题聚合的压缩事实(如「IP X 已确立的世界观条目」)
      semantic    语义召回: embedding 余弦检索(embedder 可注入; 缺省 tf-idf 兜底)
  - `MemoryStore`(sqlite 单文件) + `memory_trail` 上下文组装器
  - 写入 API: `remember(kind, key, payload, embedding=None)`; 语义检索:
    `recall(query, k)` / `recall_by_embedding(vec, k)`
  - 伪匿名约束(3O): key/payload 不含真实 PII, 用稳定化引用(如 episode_id)。

用法(服务层):
    store = MemoryStore(Path("data/memory/hevi.db"))
    store.remember("short_term", "episode_3", {"shots": 41, "verdict": "passed"})
    hits = store.recall("episode_3 的镜头数", k=3)
    ctx = memory_trail(store, "episode_3")   # → 供 LLM prompt 注入的上下文块
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)

# 短记忆保留上限(超出后淘汰最旧)。
SHORT_TERM_LIMIT = 200
_INSERT = """INSERT INTO memories (kind, key, payload, embedding, created_at)
             VALUES (?, ?, ?, ?, ?)"""
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    payload TEXT NOT NULL,
    embedding TEXT,           -- JSON 数组; NULL 表示未建向量(不可向量召回)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_kind_key ON memories (kind, key);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories (created_at);
"""


@dataclass(frozen=True)
class MemoryHit:
    id: int
    kind: str
    key: str
    payload: dict[str, Any]
    created_at: str
    score: float = 0.0  # 语义召回相似度(0-1); 非语义查询为 0


# 缺省 embedder: 词袋 tf-idf(零依赖)。注入更强者(如 CLIP/bge)可替换。
class TfIdfEmbedder:
    """轻量词袋向量(中文按字 bigram + 拉丁词), **固定维度 hashing trick**。

    固定 256 维(用 zlib.crc32 散列 token → 桶位), 避免增量词表导致的向量维度
    漂移(维度不一致时余弦=0, 会让早期写入的记忆不可召回)。仅作缺省兜底:
    语义召回质量随素材量级提升应换注入式 embedder(见 COMPETITIVE-GAP.md)。
    """

    DIM = 256

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        toks: list[str] = []
        for m in re.finditer(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]", text.lower()):
            t = m.group(0)
            if len(t) == 1 and "\u4e00" <= t <= "\u9fff":
                continue  # 单字中文跳过(信息量低)
            toks.append(t)
        # 中文按字 bigram, 捕捉词序
        han = re.findall(r"[\u4e00-\u9fff]", text.lower())
        toks.extend(a + b for a, b in zip(han, han[1:]))
        return toks

    @staticmethod
    def _bucket(token: str) -> int:
        return zlib.crc32(token.encode("utf-8")) % TfIdfEmbedder.DIM

    def embed(self, text: str) -> list[float]:
        toks = self._tokenize(text)
        counts: dict[str, int] = {}
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
        vec = [0.0] * self.DIM
        for t, c in counts.items():
            vec[self._bucket(t)] += 1.0 + math.log(c)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class MemoryStore:
    """SQLite 记忆库。线程安全(每次操作独立连接 + WAL)。"""

    def __init__(
        self,
        db_path: Path,
        *,
        embedder: Callable[[str], list[float]] | None = None,
        short_term_limit: int = SHORT_TERM_LIMIT,
    ) -> None:
        self.db_path = db_path
        self._embedder = embedder or TfIdfEmbedder().embed
        self._short_term_limit = short_term_limit
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- 写入 ----------------------------------------------------------------

    def remember(
        self,
        kind: str,
        key: str,
        payload: dict[str, Any],
        *,
        embedding: list[float] | None = None,
    ) -> int:
        """写入一条记忆。embedding 缺省由注入的 embedder 从 key+payload 摘要生成。

        3O 约束: 不得写入真实 PII; 调用方用稳定化引用(episode_id 等)作 key。
        """
        if kind not in ("short_term", "summary", "semantic"):
            raise ValueError(f"unknown memory kind: {kind}")
        if embedding is None:
            embedding = self._embedder(
                key + " " + json.dumps(payload, ensure_ascii=False)[:2000]
            )
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                _INSERT,
                (kind, key, payload_json, json.dumps(embedding), now),
            )
            new_id = int(cur.lastrowid)
            if kind == "short_term":
                conn.execute(
                    "DELETE FROM memories WHERE kind='short_term' AND id NOT IN ("
                    "SELECT id FROM memories WHERE kind='short_term' ORDER BY created_at DESC, id DESC LIMIT ?)",
                    (self._short_term_limit,),
                )
        return new_id

    # -- 查询 ----------------------------------------------------------------

    def recent(self, kind: str, *, limit: int = 20) -> list[MemoryHit]:
        rows = self._query("kind=? ORDER BY created_at DESC, id DESC LIMIT ?", (kind, limit))
        return rows

    def by_key(self, key: str, *, limit: int = 20) -> list[MemoryHit]:
        return self._query("key=? ORDER BY created_at DESC, id DESC LIMIT ?", (key, limit))

    def recall(
        self,
        query: str,
        k: int = 3,
        *,
        kinds: Sequence[str] = ("short_term", "summary", "semantic"),
    ) -> list[MemoryHit]:
        """语义召回: 用 query 的向量对库内带向量的记忆做余弦 Top-K。"""
        qvec = self._embedder(query)
        return self.recall_by_embedding(qvec, k, kinds=kinds)

    def recall_by_embedding(
        self,
        vec: Sequence[float],
        k: int = 3,
        *,
        kinds: Sequence[str] = ("short_term", "summary", "semantic"),
    ) -> list[MemoryHit]:
        hits: list[MemoryHit] = []
        placeholders = ",".join("?" * len(kinds))
        sql = (
            "SELECT id, kind, key, payload, created_at, embedding FROM memories "
            f"WHERE embedding IS NOT NULL AND kind IN ({placeholders}) "
            "ORDER BY created_at DESC"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(kinds)).fetchall()
        for row in rows:
            emb = json.loads(row["embedding"])
            sim = cosine_similarity(vec, emb)
            hits.append(
                MemoryHit(
                    id=row["id"],
                    kind=row["kind"],
                    key=row["key"],
                    payload=json.loads(row["payload"]),
                    created_at=row["created_at"],
                    score=round(sim, 4),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def _query(self, where: str, params: tuple[Any, ...]) -> list[MemoryHit]:
        sql = (
            "SELECT id, kind, key, payload, created_at FROM memories WHERE " + where
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MemoryHit(
                id=r["id"],
                kind=r["kind"],
                key=r["key"],
                payload=json.loads(r["payload"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"])

    def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memories")


def memory_trail(store: MemoryStore, topic: str, *, k: int = 3) -> str:
    """组装供 LLM prompt 注入的记忆上下文块(3O: 无 PII, 稳定引用)。

    返回 Markdown 块: 先语义召回(最近相关), 再附按 key 的最近条目。
    """
    hits = store.recall(topic, k=k)
    lines = ["# Agent 记忆(跨会话)"]
    if not hits:
        lines.append("(无相关记忆)")
        return "\n".join(lines)
    for h in hits:
        payload = json.dumps(h.payload, ensure_ascii=False)[:400]
        lines.append(
            f"- [{h.kind}] key={h.key} (sim={h.score:.2f}, {h.created_at[:19]}): {payload}"
        )
    return "\n".join(lines)


__all__ = [
    "MemoryHit",
    "MemoryStore",
    "TfIdfEmbedder",
    "cosine_similarity",
    "memory_trail",
]
