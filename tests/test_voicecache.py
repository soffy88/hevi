"""Unit tests for the Xiaoya voice cache (no ollama / CosyVoice / network).

Covers normalisation, exact + cosine matching, the CachedTTS wrapper's graceful
fallback, and the live-loop integration seam (a cached hit skips the real TTS).
"""

from __future__ import annotations

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
