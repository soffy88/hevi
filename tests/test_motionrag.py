"""Motion-RAG unit tests: retrieval, prosody, planning, query cache.

Pure logic on a synthetic index — no EmbeddingGemma model, no network.  A
`FakeEmbedder` stands in for the real embedder so the whole query path is
exercised deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hevi.live_host.avatar.motionrag import (
    IDLE_QUERY,
    Config,
    LocalIndex,
    QueryCache,
    RagDirector,
    Retriever,
    Seg,
    log_miss,
    prosody,
    split_phrases,
)


# ── fixtures ──────────────────────────────────────────
def _unit(v: np.ndarray) -> np.ndarray:
    return v / max(np.linalg.norm(v), 1e-9)


def _seg(idx, clip, kinds, vec, pose=None, peak=0, start=0, end=40):
    p = _unit(np.ones(4)) if pose is None else _unit(pose)
    return Seg(
        idx=idx,
        clip=clip,
        start=start,
        end=end,
        kinds=kinds,
        text=f"{clip} description",
        energy_peak=peak,
        video=_unit(vec),
        text_emb=_unit(vec),
        pose_first=p,
        pose_last=p,
    )


@pytest.fixture
def index() -> LocalIndex:
    rng = np.random.default_rng(0)
    a = _unit(rng.standard_normal(16))
    b = _unit(rng.standard_normal(16))
    segs = [
        _seg(0, "idle", ("idle",), a, pose=[1, 0, 0, 0]),
        _seg(1, "g_wave", ("talk", "idle"), b, pose=[0, 1, 0, 0]),
        _seg(2, "talk_a", ("talk",), a, pose=[0, 0, 1, 0]),
    ]
    return LocalIndex(segs, {"fps": 20.0, "avatar": "test"})


class FakeEmbedder:
    """Returns a fixed vector so text queries are deterministic in tests."""

    name = "fake"

    def __init__(self, vec: np.ndarray):
        self.vec = _unit(vec)

    def text(self, texts, *, query):
        return np.stack([self.vec] * len(texts))

    def images(self, imgs):
        return np.stack([self.vec] * len(imgs))

    def audio(self, paths):
        return None

    @property
    def audio_ok(self):
        return False


# ── pure helpers ──────────────────────────────────────
def test_split_phrases():
    assert split_phrases("你好，我是小雅。") == ["你好", "我是小雅。"]
    assert split_phrases("没有标点") == ["没有标点"]
    assert split_phrases("") == []


def test_prosody_stress_and_pitch():
    sr = 16000
    t = np.arange(sr) / sr
    # quiet 0.5 s, then a loud 200 Hz tone for 0.5 s
    wav = np.concatenate(
        [
            np.zeros(sr // 2, np.float32),
            0.5 * np.sin(2 * np.pi * 200 * t[: sr // 2]).astype(np.float32),
        ]
    )
    p = prosody(wav, sr, fps=20.0, text="四个字啊")
    assert p["stress_frac"] > 0.5  # loud half is at the end
    assert 150 < p["f0_hi"] < 260  # ~200 Hz tone detected
    assert p["rate"] == pytest.approx(4 / 1.0, abs=0.1)
    assert p["energy"] > 0


# ── retrieval ─────────────────────────────────────────
def test_candidates_filter_by_kind(index):
    r = Retriever(index, Config())
    assert {s.clip for s in index.candidates("idle")} == {"idle", "g_wave"}
    assert {s.clip for s in index.candidates("talk")} == {"g_wave", "talk_a"}


def test_retriever_prefers_matching_vector(index):
    r = Retriever(index, Config(w_transition=0.0, w_repeat=0.0))
    q = _unit(index.segs[2].video)  # == talk_a's vector
    ch = r.pick(q, None, "talk", None, now=0.0)
    assert ch.seg.clip == "talk_a"


def test_repeat_penalty_switches_clip(index):
    # two talk candidates (g_wave, talk_a); pick both with the same query
    cfg = Config(w_transition=0.0, w_repeat=1.0, repeat_window_s=10.0)
    r = Retriever(index, cfg)
    q = _unit(index.segs[2].video)  # favours talk_a
    first = r.pick(q, None, "talk", None, now=0.0)
    second = r.pick(q, None, "talk", None, now=0.0)  # talk_a now penalised
    assert first.seg.clip == "talk_a"
    assert second.seg.clip == "g_wave"


def test_transition_cost_can_override_similarity(index):
    # talk_a and g_wave share the same query vector score; a pose far from
    # talk_a's pose must push the pick to g_wave.
    cfg = Config(w_transition=5.0, w_repeat=0.0)
    r = Retriever(index, cfg)
    q = _unit(index.segs[2].video)
    far = _unit(-index.segs[2].pose_first)  # opposite pose
    ch = r.pick(q, None, "talk", far, now=0.0)
    assert ch.seg.clip == "g_wave"


# ── planning / director ───────────────────────────────
class FakeClip:
    def __init__(self, n):
        self.n = n

    def __len__(self):
        return self.n


def _director(index, **cfg):
    clips = {"idle": FakeClip(100), "g_wave": FakeClip(100), "talk_a": FakeClip(100)}
    emb = FakeEmbedder(index.segs[2].video)
    return RagDirector(clips, index, emb, Config(**cfg), fps=20.0)


def test_empty_candidates_fall_back_to_any(index):
    """An index with only idle clips must still serve a talk query."""
    r = Retriever(LocalIndex([index.segs[0]], {"fps": 20.0}), Config())
    ch = r.pick(_unit(index.segs[0].video), None, "talk", None, now=0.0)
    assert ch is not None and ch.seg.clip == "idle"


def test_retriever_returns_none_when_index_empty(index):
    r = Retriever(LocalIndex([], {"fps": 20.0}), Config())
    assert r.pick(_unit(np.ones(8)), None, "talk", None, now=0.0) is None


def test_refs_returns_exact_count(index):
    d = _director(index)
    refs = d.refs("talk", 57, caption="你好，我是小雅。", wav=None)
    assert len(refs) == 57
    for r in refs:
        assert r[0] in d.clips.values()  # clip object
        assert isinstance(r[1], int)


def test_idle_only_uses_idle_candidates(index):
    d = _director(index)
    refs = d.refs("idle", 30, caption="")
    assert len(refs) == 30
    used = {r[0] for r in refs}
    # idle pool is {idle, g_wave}; talk_a must never appear
    assert d.clips["talk_a"] not in used


def test_choices_logged_with_text(index):
    d = _director(index)
    d.refs("talk", 40, caption="你好，我是小雅。", wav=None)
    assert d.choices
    texts = {c["text"] for c in d.choices}
    assert "你好" in texts  # sub-phrase recorded
    assert all("score" in c and "latency_ms" in c for c in d.choices)


def test_refs_stay_inside_chosen_segment_window(index):
    """The played frames must come from the segment's own window, not frame 0
    (all segments of a clip start from the same still, which would otherwise
    make them indistinguishable at play time)."""
    segs = [
        _seg(0, "idle", ("idle",), np.ones(16), pose=[1, 0, 0, 0], start=0, end=50),
        _seg(1, "talk_a", ("talk",), np.ones(16), pose=[0, 1, 0, 0], start=30, end=70),
    ]
    idx = LocalIndex(segs, {"fps": 20.0, "avatar": "test"})
    clips = {"idle": FakeClip(100), "talk_a": FakeClip(100)}
    d = RagDirector(clips, idx, FakeEmbedder(segs[1].video), Config(), fps=20.0)
    refs = d.refs("talk", 20, caption="完整一句", wav=None)
    frames = [r[1] for r in refs]
    assert min(frames) >= 30, "no frame before the segment start"
    assert max(frames) < 70 or max(frames) == 99, "no frame past the segment end"


def test_frames_stay_within_clip_bounds(index):
    """Even a long phrase must never index past the end of a clip."""
    d = _director(index)
    refs = d.refs("talk", 500, caption="很长很长的句子，" * 12, wav=None)
    assert len(refs) == 500
    for r in refs:
        if len(r) >= 3 and r[2] is not None:  # crossfade (clip, i, clip2, j, a)
            assert 0 <= r[1] < len(r[0])
            assert 0 <= r[3] < len(r[2])
        else:
            assert 0 <= r[1] < len(r[0])


def test_time_warp_stays_within_20_percent(index):
    segs = [_seg(2, "talk_a", ("talk",), np.ones(16), pose=[0, 0, 1, 0], start=0, end=60)]
    idx = LocalIndex(segs, {"fps": 20.0, "avatar": "test"})
    clips = {"talk_a": FakeClip(100)}
    d = RagDirector(clips, idx, FakeEmbedder(np.ones(16)), Config(), fps=20.0)
    # 60-frame segment asked to cover 30 frames → must move faster, not slower
    d.refs("talk", 30, caption="短句", wav=None)
    strides = [c["stride"] for c in d.choices]
    assert all(0.8 <= s <= 1.2 for s in strides), strides


def test_miss_logged_below_threshold(index, tmp_path):
    cfg = Config(miss_threshold=10.0, queue=tmp_path / "q.jsonl")  # nothing ever clears 10
    clips = {"idle": FakeClip(100), "g_wave": FakeClip(100), "talk_a": FakeClip(100)}
    d = RagDirector(clips, index, FakeEmbedder(index.segs[2].video), cfg, fps=20.0)
    d.refs("talk", 40, caption="你好", wav=None, audio_path="/x/s00.wav")
    assert d.misses >= 1
    lines = (tmp_path / "q.jsonl").read_text().strip().splitlines()
    rec = json.loads(lines[0])
    assert rec["text"] == "你好"
    assert rec["audio"] == "/x/s00.wav"
    assert rec["best_score"] < 10.0


# ── query cache ───────────────────────────────────────
def test_query_cache_roundtrip(tmp_path):
    qc = QueryCache()
    qc.text["你好"] = np.ones(8, np.float32)
    qc.audio["你好"] = np.zeros(8, np.float32)
    qc.prosody["你好"] = {"stress_frac": 0.3, "f0_lo": 100.0}
    p = tmp_path / "q.npz"
    qc.save(p)
    back = QueryCache.load(p)
    assert np.allclose(back.text["你好"], 1.0)
    assert np.allclose(back.audio["你好"], 0.0)
    assert back.prosody["你好"]["stress_frac"] == 0.3


def test_director_uses_precomputed_query_without_embedder(index):
    clips = {"idle": FakeClip(100), "g_wave": FakeClip(100), "talk_a": FakeClip(100)}
    qc = QueryCache()
    qc.text[IDLE_QUERY] = _unit(index.segs[0].video)
    qc.text["你好"] = _unit(index.segs[2].video)
    d = RagDirector(clips, index, None, Config(), fps=20.0, queries=qc)
    refs = d.refs("talk", 40, caption="你好", wav=None)
    assert len(refs) == 40


def test_director_raises_without_embedder_or_cache(index):
    clips = {"idle": FakeClip(100), "g_wave": FakeClip(100), "talk_a": FakeClip(100)}
    d = RagDirector(clips, index, None, Config(), fps=20.0, queries=QueryCache())
    with pytest.raises(RuntimeError):
        d.refs("talk", 40, caption="你好", wav=None)


def test_log_miss_appends(tmp_path):
    cfg = Config(queue=tmp_path / "q.jsonl")
    log_miss(
        cfg,
        text="a",
        audio=Path("/x.wav"),
        duration=1.2,
        score=0.2,
        wanted="w",
        kind="talk",
        clip="g_wave",
    )
    log_miss(
        cfg, text="b", audio=None, duration=0.8, score=0.1, wanted="w", kind="talk", clip="g_wave"
    )
    lines = (tmp_path / "q.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["audio"] is None
