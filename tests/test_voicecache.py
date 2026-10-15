"""Unit tests for the Xiaoya voice cache (no ollama / CosyVoice / network).

Covers normalisation, exact + cosine matching, the CachedTTS wrapper's graceful
fallback, and the live-loop integration seam (a cached hit skips the real TTS).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from hevi.live_host.voicecache import (
    CachedTTS,
    VoiceCache,
    VoiceEntry,
    normalize,
)

N = 768


class _FakeEmb:
    """Query embedder: maps a text to a fixed direction so cosine is
    deterministic without EG2."""

    def text(self, texts, *, query):
        out = []
        for t in texts:
            if "礼物" in t or "谢谢" in t:
                out.append([1.0, 0.0] + [0.0] * (N - 2))
            else:
                out.append([0.0, 1.0] + [0.0] * (N - 2))
        return np.asarray(out, dtype=np.float32)


def _entry(eid, text, motion="talk_a", category="misc", emb=None, wav_exists=True):
    p = Path(f"/data/soffy/voicecache/wav/{eid}.wav")
    if wav_exists:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(b"RIFF")  # stand-in; only existence is checked
    return VoiceEntry(
        id=eid, text=text, wav=p, duration=2.0, motion=motion, category=category, text_emb=emb
    )


def _cache(entries, with_matrix=True):
    vc = VoiceCache(root=Path("/data/soffy/voicecache"), threshold=0.82)
    vc.entries = entries
    vc._by_norm = {e.norm: e for e in entries}
    if with_matrix and all(e.text_emb is not None for e in entries):
        vc._text_matrix = np.stack([e.text_emb for e in entries])
    return vc


# ── normalisation ─────────────────────────────────────────────
def test_normalize_strips_label_and_punct():
    assert normalize("【AI生成】欢迎来到小雅的直播间。") == "欢迎来到小雅的直播间"
    assert normalize("欢迎来到小雅的直播间") == "欢迎来到小雅的直播间"
    assert normalize(" 你好, 世界! ") == "你好世界"


def test_normalize_is_case_insensitive_for_latin():
    assert normalize("Hello World") == normalize("hello world")


# ── loading a real library off disk ───────────────────────────────
def test_voicecache_loads_library_and_builds_matrix(tmp_path):
    """VoiceCache(root=...) must actually load manifest+index and pair each id
    with its own vector.  (A missing audio_emb field on VoiceEntry made every
    construction raise, and a row-order mismatch would silently misalign them.)"""
    import numpy as np

    wav_dir = tmp_path / "wav"
    wav_dir.mkdir()
    entries = [("a", "欢迎来到小雅的直播间"), ("b", "谢谢哥哥的礼物")]
    for eid, _ in entries:
        (wav_dir / f"{eid}.wav").write_bytes(b"RIFF")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "id": e,
                        "text": t,
                        "wav": f"wav/{e}.wav",
                        "duration": 1.0,
                        "motion": "talk_a",
                        "category": "greeting",
                    }
                    for e, t in entries
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # entry 'a' is a greeting line, entry 'b' the gift line.  Give each the
    # direction _FakeEmb uses for its topic (col 0 = 谢谢/礼物, col 1 = else).
    # The npz deliberately lists 'b' FIRST, i.e. NOT the manifest order, so a
    # row-order bug would hand 'a' the b-vector and vice versa.
    np.savez_compressed(
        tmp_path / "index.npz",
        ids=np.array(["b", "a"]),
        text=np.asarray([[1.0] + [0.0] * 767, [0.0, 1.0] + [0.0] * 766], dtype=np.float32),
    )

    vc = VoiceCache(root=tmp_path, threshold=0.99, embedder=_FakeEmb())
    assert len(vc.entries) == 2
    assert vc.ready
    assert vc._text_matrix is not None and vc._text_matrix.shape == (2, 768)
    # npz order is [b, a] but manifest order is [a, b], and a positional bug
    # would hand 'a' the col-0 (gift) vector.  Keying by ID keeps it right:
    # 'a' (greeting) → col 1, 'b' (gift) → col 0.
    assert vc._text_matrix[0, 1] > 0.9 and vc._text_matrix[0, 0] < 0.1
    assert vc._text_matrix[1, 0] > 0.9 and vc._text_matrix[1, 1] < 0.1
    # …and the gift-side paraphrase must retrieve the gift entry, not the greeting
    hit, score = vc.match("谢谢大哥的礼物")
    assert hit is not None and hit.id == "b", (hit, score)


# ── matching ─────────────────────────────────────────────────
def test_exact_hit():
    vc = _cache([_entry("a", "谢谢哥哥的礼物。", "g_heart", "gift_thanks")])
    hit = vc.lookup("谢谢哥哥的礼物。")
    assert hit is not None and hit.id == "a"


def test_normalized_hit_ignores_punctuation():
    vc = _cache([_entry("a", "欢迎来到小雅的直播间", "g_wave", "greeting")])
    assert vc.lookup("欢迎来到小雅的直播间！").id == "a"
    assert vc.lookup("【AI生成】欢迎来到小雅的直播间。").id == "a"


def test_miss_below_threshold_returns_none():
    # no vectors present → cosine path unavailable → miss
    vc = _cache([_entry("a", "完全不同的话xyz", emb=None)], with_matrix=False)
    assert vc.lookup("今天天气真好啊") is None


def test_miss_logs_and_counts():
    vc = _cache([_entry("a", "完全不同的话xyz", emb=None)], with_matrix=False)
    before = vc.misses
    assert vc.lookup("今天天气真好啊") is None
    assert vc.misses == before + 1


# ── cosine path (needs a query embedder) ─────────────────────
def test_cosine_hit_uses_injected_embedder():
    """A paraphrased reply must be able to score against the library: without a
    query embedder the cosine path is dead and only exact matches ever hit."""
    import numpy as np

    v = np.zeros(N, dtype=np.float32)
    v[0] = 1.0  # library vector for a gift-thanks line
    vc = _cache([_entry("a", "谢谢哥哥的礼物", "g_heart", "gift_thanks", emb=v)])
    vc._emb = _FakeEmb()

    hit, score = vc.match("谢谢大哥的礼物呀")  # a paraphrase (no exact match)
    assert hit is not None and hit.id == "a" and score >= vc.threshold


def test_cosine_miss_when_embedder_absent():
    """Default (no embedder) = live path: paraphrase does not hit, never crashes."""
    import numpy as np

    v = np.zeros(N, dtype=np.float32)
    v[0] = 1.0
    vc = _cache([_entry("a", "谢谢哥哥的礼物", "g_heart", "gift_thanks", emb=v)])
    assert vc._emb is None
    hit, score = vc.match("谢谢大哥的礼物呀")
    assert hit is None and score == 0.0


# ── CachedTTS wrapper ────────────────────────────────────────
class _FakeTTS:
    name = "fake_tts"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def synthesize(self, text, output_path):
        self.calls += 1
        Path(output_path).write_bytes(b"RIFF")
        return Path(output_path)


def test_cachedtts_hit_skips_real_tts():
    entries = [_entry("a", "谢谢哥哥的礼物。", "g_heart", "gift_thanks")]
    vc = _cache(entries)
    backend = _FakeTTS()
    wrap = CachedTTS(backend, root=Path("/data/soffy/voicecache"))
    wrap.cache = vc  # inject the in-memory cache
    wrap.enabled = True
    out = wrap.synthesize("谢谢哥哥的礼物。", "/tmp/vc_hit_out.wav")
    assert out.exists()
    assert backend.calls == 0  # real TTS skipped on a hit


def test_cachedtts_miss_uses_real_tts_and_logs():
    import tempfile

    entries = [_entry("a", "完全不相关的缓存句xyz", emb=None)]
    vc = _cache(entries, with_matrix=False)
    backend = _FakeTTS()
    wrap = CachedTTS(backend, root=Path("/data/soffy/voicecache"))
    wrap.cache = vc
    wrap.enabled = True
    tmp = tempfile.mkdtemp()
    wrap.synthesize("一句全新的话", Path(tmp) / "out.wav")
    assert backend.calls == 1
    # a miss was logged to the queue
    q = Path("/data/soffy/voicecache/miss_queue.jsonl")
    assert q.exists() and "一句全新的话" in q.read_text(encoding="utf-8")


def test_cachedtts_disabled_falls_back():
    backend = _FakeTTS()
    wrap = CachedTTS(backend, root=Path("/data/soffy/voicecache"))
    wrap.enabled = False  # no library loaded
    wrap.synthesize("任意的话", "/tmp/vc_fallback.wav")
    assert backend.calls == 1


# ── voicecache_fill normalisation must match the library's ────────────────
def test_fill_normalize_matches_library():
    """voicecache_fill.py runs under the CosyVoice venv and cannot import the
    hevi package, so it carries its own _normalize.  It MUST behave identically
    to VoiceCache.normalize, otherwise dedup would let duplicate entries in."""
    import importlib.util

    p = Path("/data/soffy/projects/hevi-live/hevi/live_host/voicecache/voicecache_fill.py")
    spec = importlib.util.spec_from_file_location("voicecache_fill", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # no hevi deps: safe to exec standalone
    for t in [
        "谢谢哥哥的礼物。",
        "【AI生成】欢迎来到小雅的直播间。",
        " 你好, 世界! ",
        "Hello World",
        "晚安～明天见",
        "、（测试）；",
        "",
    ]:
        assert mod._normalize(t) == normalize(t), t
