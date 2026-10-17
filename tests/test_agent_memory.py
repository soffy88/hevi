"""Agent 向量记忆系统测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.memory import (
    AgentMemory,
    FileVectorStore,
    LocalHashEmbedding,
    MemoryEntry,
)
from hevi.memory.vector_store import _cosine_similarity


# ── Embedding ────────────────────────────────────────────────────────────────


def test_local_hash_embedding_deterministic() -> None:
    """同一段文本多次 embed 得到相同向量。"""
    emb = LocalHashEmbedding(dimensions=64)
    v1 = emb.embed("hello world")
    v2 = emb.embed("hello world")
    assert v1 == v2
    assert len(v1) == 64


def test_local_hash_embedding_different_texts_differ() -> None:
    """不同文本得到不同向量。"""
    emb = LocalHashEmbedding(dimensions=64)
    v1 = emb.embed("角色A刺杀秦始皇")
    v2 = emb.embed("角色B在市集买酒")
    assert v1 != v2


def test_local_hash_embedding_normalized() -> None:
    """向量 L2 归一化(模长 ≈ 1.0)。"""
    import math

    emb = LocalHashEmbedding(dimensions=128)
    v = emb.embed("test normalization")
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-6


def test_local_hash_embedding_batch() -> None:
    """批量 embed 与逐个 embed 结果一致。"""
    emb = LocalHashEmbedding(dimensions=32)
    texts = ["a", "b", "c"]
    batch = emb.embed_batch(texts)
    single = [emb.embed(t) for t in texts]
    assert batch == single


# ── Cosine similarity ────────────────────────────────────────────────────────


def test_cosine_similarity_identical() -> None:
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal() -> None:
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_similarity_opposite() -> None:
    assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) - (-1.0)) < 1e-9


def test_cosine_similarity_zero_vector() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_similarity_dimension_mismatch() -> None:
    assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ── VectorStore ──────────────────────────────────────────────────────────────


def test_file_vector_store_add_and_count(tmp_path: Path) -> None:
    store = FileVectorStore(base_dir=tmp_path, namespace="test")
    emb = LocalHashEmbedding(dimensions=32)
    entry = MemoryEntry(id="", text="hello", embedding=emb.embed("hello"))
    store.add(entry)
    assert store.count() == 1


def test_file_vector_store_persistence(tmp_path: Path) -> None:
    """添加 → 新建 store 实例 → 数据仍在。"""
    store1 = FileVectorStore(base_dir=tmp_path, namespace="persist")
    emb = LocalHashEmbedding(dimensions=32)
    store1.add(MemoryEntry(id="", text="alpha", embedding=emb.embed("alpha")))
    store1.add(MemoryEntry(id="", text="beta", embedding=emb.embed("beta")))

    store2 = FileVectorStore(base_dir=tmp_path, namespace="persist")
    assert store2.count() == 2


def test_file_vector_store_search_returns_closest(tmp_path: Path) -> None:
    store = FileVectorStore(base_dir=tmp_path, namespace="search")
    emb = LocalHashEmbedding(dimensions=64)

    texts = ["秦始皇统一六国", "荆轲刺秦王", "卫鞅变法图强", "商鞅立木取信"]
    for t in texts:
        store.add(MemoryEntry(id="", text=t, embedding=emb.embed(t)))

    # 搜索应返回结果(因为 hash embedding 不是语义的,只验证不崩)
    results = store.search(emb.embed("秦始皇"), top_k=2)
    assert len(results) == 2
    assert all(isinstance(r, MemoryEntry) for r in results)


def test_file_vector_store_metadata_filter(tmp_path: Path) -> None:
    store = FileVectorStore(base_dir=tmp_path, namespace="filter")
    emb = LocalHashEmbedding(dimensions=32)

    store.add(
        MemoryEntry(id="", text="a", embedding=emb.embed("a"), metadata={"type": "event"})
    )
    store.add(
        MemoryEntry(id="", text="b", embedding=emb.embed("b"), metadata={"type": "character"})
    )
    store.add(
        MemoryEntry(id="", text="c", embedding=emb.embed("c"), metadata={"type": "event"})
    )

    results = store.search(emb.embed("any"), top_k=10, type="event")
    assert len(results) == 2
    assert all(r.metadata["type"] == "event" for r in results)


def test_file_vector_store_delete(tmp_path: Path) -> None:
    store = FileVectorStore(base_dir=tmp_path, namespace="del")
    emb = LocalHashEmbedding(dimensions=32)
    e = MemoryEntry(id="to-delete", text="x", embedding=emb.embed("x"))
    store.add(e)
    assert store.count() == 1
    assert store.delete("to-delete") is True
    assert store.count() == 0
    assert store.delete("nonexistent") is False


def test_file_vector_store_clear(tmp_path: Path) -> None:
    store = FileVectorStore(base_dir=tmp_path, namespace="clear")
    emb = LocalHashEmbedding(dimensions=32)
    for t in ["a", "b", "c"]:
        store.add(MemoryEntry(id="", text=t, embedding=emb.embed(t)))
    assert store.count() == 3
    store.clear()
    assert store.count() == 0


# ── AgentMemory ──────────────────────────────────────────────────────────────


def test_agent_memory_remember_and_recall(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="test-am",
        store=FileVectorStore(base_dir=tmp_path, namespace="test-am"),
    )
    entry = mem.remember("秦始皇焚书坑儒", {"type": "event"})
    assert entry.id
    assert mem.store.count() == 1

    results = mem.recall("秦始皇", top_k=3)
    assert len(results) == 1
    assert results[0].text == "秦始皇焚书坑儒"


def test_agent_memory_short_term(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="st",
        store=FileVectorStore(base_dir=tmp_path, namespace="st"),
        max_short_term=3,
    )
    mem.push_short_term({"role": "user", "content": "你好"})
    mem.push_short_term({"role": "assistant", "content": "你好！"})
    assert len(mem.get_short_term()) == 2
    assert mem.store.count() == 0  # 短期未持久化

    # 超出上限 → 自动 flush 全部短期记忆到长期
    mem.push_short_term({"role": "user", "content": "开始"})
    mem.push_short_term({"role": "assistant", "content": "好的"})
    # 第4条触发 flush(max_short_term=3),全部 4 条转入长期,短期清空
    assert mem.store.count() == 4
    assert len(mem.get_short_term()) == 0


def test_agent_memory_flush_short_term(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="flush",
        store=FileVectorStore(base_dir=tmp_path, namespace="flush"),
    )
    mem.push_short_term({"content": "msg1"})
    mem.push_short_term({"content": "msg2"})
    count = mem.flush_short_term()
    assert count == 2
    assert mem.store.count() == 2
    assert len(mem.get_short_term()) == 0


def test_agent_memory_summarize_session(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="summary",
        store=FileVectorStore(base_dir=tmp_path, namespace="summary"),
    )
    messages = [
        {"role": "user", "content": "生成第一集剧本"},
        {"role": "assistant", "content": "已生成12场剧本"},
        {"role": "user", "content": "修改第3场对白"},
    ]
    entry = mem.summarize_session(messages, session_id="sess-1")
    assert entry.metadata["memory_type"] == "session_summary"
    assert entry.metadata["message_count"] == 3
    assert mem.store.count() == 1


def test_agent_memory_stats(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="stats",
        store=FileVectorStore(base_dir=tmp_path, namespace="stats"),
    )
    mem.remember("test")
    mem.push_short_term({"content": "x"})
    s = mem.stats()
    assert s["namespace"] == "stats"
    assert s["long_term_count"] == 1
    assert s["short_term_count"] == 1
    assert s["embedding_dim"] == 128


def test_agent_memory_clear_all(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="clr",
        store=FileVectorStore(base_dir=tmp_path, namespace="clr"),
    )
    mem.remember("long term")
    mem.push_short_term({"content": "short term"})
    mem.clear_all()
    assert mem.store.count() == 0
    assert len(mem.get_short_term()) == 0


def test_agent_memory_remember_batch(tmp_path: Path) -> None:
    mem = AgentMemory(
        namespace="batch",
        store=FileVectorStore(base_dir=tmp_path, namespace="batch"),
    )
    entries = mem.remember_batch([
        ("事件A: 商鞅变法", {"type": "event"}),
        ("事件B: 立木取信", {"type": "event"}),
        ("角色: 卫鞅", {"type": "character"}),
    ])
    assert len(entries) == 3
    assert mem.store.count() == 3


def test_memory_entry_roundtrip() -> None:
    """MemoryEntry → dict → from_dict 无损。"""
    e = MemoryEntry(id="abc", text="hello", embedding=[0.1, 0.2], metadata={"k": "v"})
    d = e.to_dict()
    e2 = MemoryEntry.from_dict(d)
    assert e2.id == e.id
    assert e2.text == e.text
    assert e2.embedding == e.embedding
    assert e2.metadata == e.metadata
