"""hevi.memory 测试 —— 跨会话记忆三档 + 语义召回(差距 A3)。

覆盖: 写入/查询/短记忆淘汰/语义召回排序/注入 embedder/非法 kind/记忆上下文块/PII 约束。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.memory.store import (
    MemoryStore,
    TfIdfEmbedder,
    cosine_similarity,
    memory_trail,
)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "mem.db")


def test_remember_and_recent(store: MemoryStore):
    store.remember("short_term", "episode_3", {"shots": 41, "verdict": "passed"})
    store.remember("summary", "worldview", {"rule": "magic costs blood"})
    recent = store.recent("short_term")
    assert len(recent) == 1
    assert recent[0].payload["shots"] == 41
    assert recent[0].kind == "short_term"
    assert store.count() == 2


def test_by_key(store: MemoryStore):
    store.remember("semantic", "subject_ada", {"trait": "loyal"})
    store.remember("semantic", "subject_ada", {"trait": "quiet"})
    hits = store.by_key("subject_ada")
    assert len(hits) == 2
    assert hits[0].payload == {"trait": "quiet"}  # 最新在前


def test_short_term_limit_evicts_oldest(store: MemoryStore):
    for i in range(205):
        store.remember("short_term", f"ev_{i}", {"i": i})
    recent = store.recent("short_term", limit=500)
    assert len(recent) == 200
    # 最旧 5 条被淘汰
    assert all(h.payload["i"] >= 5 for h in recent)


def test_recall_semantic_ordering(store: MemoryStore):
    store.remember("semantic", "a", {"topic": "sunset over the ocean beach"})
    store.remember("semantic", "b", {"topic": "quantum physics equations"})
    hits = store.recall("beach sunset", k=1)
    assert hits and hits[0].key == "a"
    assert 0.0 <= hits[0].score <= 1.0


def test_recall_respects_kinds_filter(store: MemoryStore):
    store.remember("summary", "s1", {"topic": "winter snow"}, embedding=[1.0, 0.0])
    store.remember("short_term", "st1", {"topic": "winter snow"}, embedding=[1.0, 0.0])
    hits = store.recall("winter", k=5, kinds=("summary",))
    assert all(h.kind == "summary" for h in hits)


def test_recall_empty_store(tmp_path: Path):
    s = MemoryStore(tmp_path / "m.db")
    assert s.recall("anything") == []
    assert s.recent("short_term") == []


def test_injectable_embedder(tmp_path: Path):
    def fake_embed(text: str) -> list[float]:
        return [1.0 if "red" in text else 0.0, 0.5]

    s = MemoryStore(tmp_path / "m.db", embedder=fake_embed)
    s.remember("semantic", "r", {"c": "red car"}, embedding=[1.0, 0.5])
    s.remember("semantic", "g", {"c": "green car"}, embedding=[0.0, 0.5])
    hits = s.recall_by_embedding([1.0, 0.5], k=1)
    assert hits[0].key == "r"
    # 用同一注入 embedder 的文本召回也应命中 red
    hits2 = s.recall("the red one", k=1)
    assert hits2[0].key == "r"


def test_unknown_kind_raises(store: MemoryStore):
    with pytest.raises(ValueError):
        store.remember("nope", "k", {})


def test_cosine_similarity():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], []) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


def test_tfidf_embedder_deterministic():
    e = TfIdfEmbedder()
    v1 = e.embed("sunset over the ocean")
    v2 = e.embed("sunset over the ocean")
    v3 = e.embed("quantum physics")
    assert v1 == v2
    assert cosine_similarity(v1, v1) > 0.99
    assert cosine_similarity(v1, v3) < cosine_similarity(v1, v2)


def test_memory_trail_assembly(store: MemoryStore):
    store.remember("semantic", "subject_ada", {"trait": "loyal"}, embedding=[1.0, 0.0])
    trail = memory_trail(store, "subject ada")
    assert "# Agent 记忆" in trail
    assert "subject_ada" in trail
    assert "loyal" in trail
    assert memory_trail(store, "noise query") != ""


def test_no_pii_in_payload(store: MemoryStore):
    # 3O 约束验证: 写入口禁止真实 PII 语义——测试断言 payload 只含稳定引用
    store.remember("short_term", "episode_7", {"verdict": "passed", "episode_id": "E7"})
    hits = store.recent("short_term")
    joined = str(hits[0].payload).lower()
    for forbidden in ("phone", "id_card", "real_name"):
        assert forbidden not in joined


def test_clear(store: MemoryStore):
    store.remember("short_term", "k", {"v": 1})
    store.clear()
    assert store.count() == 0
