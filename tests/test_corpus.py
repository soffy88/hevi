"""素材语料库(corpus)测试:收录/检索/MMR/翻译退化(不依赖网络与模型)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.sourcing.corpus import ClipRecord, Corpus, _contains_cjk


@pytest.fixture
def corpus(tmp_path: Path) -> Corpus:
    """预置 3 条带假嵌入的语料(零网络/模型)。"""
    c = Corpus(root=tmp_path)
    import numpy as np

    # 三个互不相同的 512 维单位向量
    rng = np.random.default_rng(42)
    embs = rng.standard_normal((3, 512))
    embs /= np.linalg.norm(embs, axis=1, keepdims=True)
    for i, name in enumerate(["cave_fire.mp4", "skull_closeup.mp4", "city_street.mp4"]):
        rec = ClipRecord(
            clip_id=f"clip_{i}",
            source="local",
            source_id=name,
            source_url=str(tmp_path / name),
            local_path=f"clips/{name}",
            query=name,
            title=name,
        )
        c.records.append(rec)
        c._embeddings.append(embs[i].tolist())
    return c


def test_save_and_load_roundtrip(tmp_path: Path):
    c = Corpus(root=tmp_path)
    c.records.append(
        ClipRecord(
            clip_id="c1", source="local", source_id="x", source_url="",
            local_path="clips/x.mp4",
        )
    )
    c._embeddings.append([0.0] * 512)
    c.save()
    loaded = Corpus.load(tmp_path)
    assert loaded.size == 1
    assert loaded.records[0].clip_id == "c1"
    assert len(loaded._embeddings) == 1


def test_rank_for_slot_semantic_hit(corpus: Corpus, monkeypatch):
    # 语义命中:mock CLIP 文本嵌入 = clip_0 的视觉嵌入(即该槽描述精确匹配 clip_0)。
    monkeypatch.setattr(corpus, "_text_emb", lambda q: corpus._embeddings[0])
    hits = corpus.rank_for_slot("cave fire warm light", top_k=3)
    assert hits[0]["clip_id"] == "clip_0"
    assert hits[0]["score"] > 0.9  # 自匹配
    assert hits[0]["local_path"] == "clips/cave_fire.mp4"


def test_rank_for_slot_returns_best_abs_path(corpus: Corpus, tmp_path: Path):
    # best_for_slot 需要真实文件
    (tmp_path / "clips").mkdir(parents=True, exist_ok=True)
    (tmp_path / "clips" / "cave_fire.mp4").write_bytes(b"x")
    hit = corpus.best_for_slot("cave fire")
    assert hit is not None
    assert hit["local_abs_path"].endswith("cave_fire.mp4")


def test_find_similar_set_diversity(corpus: Corpus):
    # 种子 clip_0 → 集合不含种子自身,数量 ≤ count
    res = corpus.find_similar_set("clip_0", count=2)
    assert len(res) == 2
    assert all(r["clip_id"] != "clip_0" for r in res)


def test_diversify_removes_redundancy(corpus: Corpus):
    ids = ["clip_0", "clip_1", "clip_2"]
    out = corpus.diversify(ids)
    assert len(out) == 3
    assert set(out) == set(ids)  # 不丢素材,只重排


def test_contains_cjk():
    assert _contains_cjk("洞内火光")
    assert not _contains_cjk("cave fire")


def test_to_english_fallback_on_unavailable(monkeypatch):
    from hevi.sourcing.corpus import _to_english

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("no ollama")),
    )
    # 失败 → 原样返回(退化,不抛)
    assert _to_english("洞内火光") == "洞内火光"


def test_add_local_video_reindexes(tmp_path: Path):

    # 造一个最小可被 ffmpeg 抽帧的素材太贵 —— 验证文件复制 + 元数据(嵌入失败降级)
    c = Corpus(root=tmp_path)
    src = tmp_path / "src.mp4"
    src.write_bytes(b"fake-video-bytes")
    rec = c.add_local_video(src, title="T", query="q")
    assert rec.clip_id.startswith("local_")
    assert (tmp_path / rec.local_path).exists()
    assert len(c._embeddings) == 1  # 嵌入失败 → 零向量,但收录成功
