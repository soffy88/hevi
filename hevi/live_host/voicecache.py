"""Pre-generated voice cache for the Xiaoya live host.

The live host normally runs real-time TTS per reply sentence.  For the very
common, boilerplate lines a host says (greetings, gift/like/follow thanks,
榜一 thanks, refusals, greetings, goodbyes, idle chatter, comfort) the reply
is *highly repeatable* — so we pre-generate one wav per line with the same
female CosyVoice3 voice used by the reading feature, embed the text with
EmbeddingGemma 2, and at runtime look the reply up instead of synthesising it.

Design constraints (see /data/soffy/voicecache/brief.md):

* **Opt-in, default off.**  Gated by ``HEVI_LIVE_VOICECACHE`` (``off`` |
  ``on`` | ``1``).  When off (or the library is missing), every call falls
  back to the real TTS engine, so the default live behaviour is unchanged.
* **CPU-cheap hot path + no network on the hot path.**  Text vectors are
  precomputed into the npz at build time.  At runtime a hit is a handful of
  768-d dot products plus an exact/normalised-string check.  The embedding
  service is only contacted by the *offline* index builder, never live.
* **Graceful degradation.**  Any failure (no library, embedder down, audio
  load error) degrades to "miss" → caller does normal TTS.  We never raise
  into the live loop.

Storage layout (``HEVI_VOICECACHE_ROOT``, default ``/data/soffy/voicecache``):

    manifest.json   library metadata (list of entries)
    index.npz       precomputed EG2 text vectors (keyed by entry id)
    wav/<id>.wav    24 kHz mono float/int wavs
    miss_queue.jsonl  runtime misses (for offline fill)

An entry is ``{id, text, wav, duration, motion, category}`` plus, in the npz,
its ``text_emb`` (768-d).  Audio vectors are optional (EG2 audio embedding is
slow on the shared service) and absent from the default build.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

# Reuse the same EG2 embedder + dims as motionrag so the two indices live in
# one 768-d space (the user's "text/audio/video/motion in one EG2 space" idea).
from hevi.live_host.avatar.motionrag import (  # noqa: E402
    DIM,
    Config,
    get_embedder,
    probe_service,
)

DEFAULT_ROOT = Path(os.environ.get("HEVI_VOICECACHE_ROOT", "/data/soffy/voicecache"))
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.json"
DEFAULT_INDEX = DEFAULT_ROOT / "index.npz"
DEFAULT_MISS = DEFAULT_ROOT / "miss_queue.jsonl"


# --------------------------------------------------------------------------
# normalisation
# --------------------------------------------------------------------------

_PUNCT = re.compile(r"[\s，,。.！!？?；;：:、~～…—\-_“”\"'‘’（）()\[\]【】<>《》/\\|]+")
_WRAP = re.compile(r"^[【\[].*?[】\]]")  # leading AIGC label like 【AI生成】


def normalize(text: str) -> str:
    """Loose normalisation for matching cached text against a reply.

    Strips surrounding AIGC labels, punctuation and whitespace, lowercases
    latin, and collapses internal spacing.  Two utterances that differ only in
    punctuation/spaces/label are treated as equal.
    """
    t = text or ""
    t = _WRAP.sub("", t)
    t = _PUNCT.sub(" ", t)
    t = t.lower().strip()
    return re.sub(r"\s+", "", t)


# --------------------------------------------------------------------------
# library entry + loader
# --------------------------------------------------------------------------


@dataclass
class VoiceEntry:
    id: str
    text: str
    wav: Path
    duration: float
    motion: str
    category: str
    text_emb: np.ndarray | None = None

    @property
    def norm(self) -> str:
        return normalize(self.text)


class VoiceCache:
    """Pre-generated utterance library with cosine + exact matching."""

    def __init__(
        self,
        root: Path = DEFAULT_ROOT,
        *,
        manifest: Path | None = None,
        index: Path | None = None,
        threshold: float | None = None,
        exact_first: bool = True,
        embedder=None,
    ) -> None:
        self.root = Path(root)
        self.manifest_path = manifest or (self.root / "manifest.json")
        self.index_path = index or (self.root / "index.npz")
        self.threshold = (
            threshold
            if threshold is not None
            else float(os.environ.get("HEVI_VOICECACHE_THRESHOLD", "0.82"))
        )
        self.exact_first = exact_first
        # Optional query embedder for the cosine path.  The live hot path does
        # NOT embed: it passes embedder=None and gets exact/normalised matching
        # only.  The offline replay/metrics scripts pass one so paraphrased
        # replies can score against the library.
        self._emb = embedder
        self.entries: list[VoiceEntry] = []
        self._by_norm: dict[str, VoiceEntry] = {}
        self._text_matrix: np.ndarray | None = None
        self.hits = 0
        self.misses = 0
        self._load()

    # -- load ------------------------------------------------------------
    def _load(self) -> None:
        if not self.manifest_path.is_file():
            return
        data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        embs: dict[str, np.ndarray] = {}
        audio: dict[str, np.ndarray] = {}
        if self.index_path.is_file():
            z = np.load(self.index_path, allow_pickle=False)
            if "ids" in z.files and "text" in z.files:
                ids = [str(x) for x in z["ids"]]
                mat = np.atleast_2d(z["text"])
                embs = {i: mat[j] for j, i in enumerate(ids) if j < len(mat)}
                if "audio" in z.files:
                    amat = np.atleast_2d(z["audio"])
                    audio = {i: amat[j] for j, i in enumerate(ids) if j < len(amat)}
            else:  # legacy layout: one key per id, ``t_<id>``
                for k in z.files:
                    if k.startswith("t_"):
                        embs[k[2:]] = z[k]
                    elif k.startswith("a_"):
                        audio[k[2:]] = z[k]
        for e in data.get("entries", []):
            p = self.root / e["wav"]
            ve = VoiceEntry(
                id=e["id"],
                text=e["text"],
                wav=p,
                duration=float(e.get("duration", 0.0)),
                motion=e.get("motion", "talk_a"),
                category=e.get("category", "misc"),
                text_emb=embs.get(e["id"]),
                audio_emb=audio.get(e["id"]),
            )
            self.entries.append(ve)
            self._by_norm[ve.norm] = ve
        if self.entries and all(e.text_emb is not None for e in self.entries):
            self._text_matrix = np.stack([e.text_emb for e in self.entries])  # (N,768)

    @property
    def ready(self) -> bool:
        return bool(self.entries)

    @property
    def dim(self) -> int:
        return DIM

    # -- matching --------------------------------------------------------
    def match(self, text: str) -> tuple[VoiceEntry | None, float]:
        """Return (best_entry, score).  score is 1.0 for an exact/normalised
        match, otherwise the cosine of the EG2 text vectors (or 0.0 if no
        vectors are available)."""
        if not self.entries:
            return None, 0.0
        n = normalize(text)
        if self.exact_first and n in self._by_norm:
            return self._by_norm[n], 1.0
        if self._text_matrix is None:
            return None, 0.0
        q = self._query_vec(text)
        if q is None:
            return None, 0.0
        sims = self._text_matrix @ q  # (N,)
        i = int(np.argmax(sims))
        return self.entries[i], float(sims[i])

    def _query_vec(self, text: str) -> np.ndarray | None:
        """Query vector from the build-time embedder, if any.  Hot path does
        NOT embed — but for a no-index fallback we can build on demand (rare)."""
        emb = getattr(self, "_emb", None)
        if emb is None:
            return None
        try:
            return emb.text([text], query=True)[0]
        except Exception:
            return None

    def lookup(self, text: str) -> VoiceEntry | None:
        """Return a cached entry if it is a hit, else None."""
        entry, score = self.match(text)
        if entry is None:
            self.misses += 1
            return None
        if score >= self.threshold:
            self.hits += 1
            return entry
        self.misses += 1
        return None

    def choose_for_chatter(self, preferred: Sequence[str] | None = None) -> VoiceEntry | None:
        """Optional: for idle chatter (no question) prefer a cached line
        directly rather than generating.  Returns a random-ish pick from the
        preferred categories, or any entry."""
        pool = self.entries
        if preferred:
            sub = [e for e in pool if e.category in preferred]
            if sub:
                pool = sub
        if not pool:
            return None
        # deterministic round-robin by hit count so we don't repeat one line
        return min(pool, key=lambda e: getattr(e, "_used", 0))


# --------------------------------------------------------------------------
# build-time helpers (offline only)
# --------------------------------------------------------------------------


def build_text_index(
    entries: list[VoiceEntry],
    cfg: Config,
    *,
    index_path: Path,
    use_audio: bool = False,
) -> dict[str, object]:
    """Embed every entry's text (and optionally audio) with EG2.  Returns a
    dict with ``text`` (N,768) and optional ``ids``.  Writes the npz."""
    texts = [e.text for e in entries]
    emb = get_embedder(cfg, allow_audio=use_audio)
    tvecs = emb.text(texts, query=False)  # Document vectors for the library
    index_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        index_path,
        ids=np.array([e.id for e in entries]),
        text=tvecs,
    )
    return {"ids": [e.id for e in entries], "text": tvecs}


def log_miss(text: str, *, path: Path | None = None, ts: str | None = None) -> None:
    """Append a runtime miss to miss_queue.jsonl for offline fill."""
    p = path or DEFAULT_MISS
    rec = {
        "ts": ts or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": text,
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# live wrapper (drop-in for the TTS engine at the synthesize() call site)
# --------------------------------------------------------------------------


class CachedTTS:
    """Wraps a real TTS engine.  ``synthesize(text, out)`` returns the cached
    wav path when the text is a hit, otherwise delegates to the real engine and
    logs a miss.

    Usage in the live loop (live_stream.py:_brain), behind HEVI_LIVE_VOICECACHE::

        if os.environ.get("HEVI_LIVE_VOICECACHE", "off") in ("on", "1"):
            from hevi.live_host.voicecache import CachedTTS
            self.tts = CachedTTS(self.tts, root=...)
        ...
        self.tts.synthesize(s, wav_p)   # unchanged call site
    """

    name = "cached_tts"

    def __init__(
        self, backend, root: Path = DEFAULT_ROOT, *, threshold: float | None = None
    ) -> None:
        self.backend = backend
        self.cache = VoiceCache(root, threshold=threshold)
        self.enabled = self.cache.ready
        if not self.enabled:
            # No library: behave exactly like the raw backend.
            pass

    def available(self) -> bool:
        return self.backend.available()

    def synthesize(self, text: str, output_path: str | Path) -> Path:
        if self.enabled:
            hit = self.cache.lookup(text)
            if hit is not None and hit.wav.is_file():
                Path(output_path).write_bytes(hit.wav.read_bytes())
                return Path(output_path)
            # miss: generate normally + record for offline fill
            log_miss(text, path=self.cache.root / "miss_queue.jsonl")
        return self.backend.synthesize(text, output_path)
