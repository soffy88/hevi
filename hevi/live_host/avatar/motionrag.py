"""Retrieval-based motion ("motion RAG") for the Xiaoya half-body avatar.

The base `Director` (halfbody.py) picks motion clips with weighted-random pools
plus regex cues.  This module replaces that with *retrieval*: every candidate
motion segment is embedded (video frames + a hand-written description) with
Google EmbeddingGemma 2, and at render time each spoken sub-phrase is embedded
(text + optional audio) and the best-matching segment is chosen, subject to a
pose-transition cost and a repetition penalty.

Design constraints (see /data/soffy/motionrag/brief.md):

* **CPU-cheap hot path.**  Library embeddings are precomputed into an npz
  (`LocalIndex`); a per-sentence query is a handful of 768-d dot products.
* **Two storage backends** behind one interface: `LocalIndex` (npz, used at
  render time) and `StratumIndex` (AII/Stratum media-asset API, used only at
  index-build time — see /data/soffy/motionrag/stratum_contract.md).
* **Two embedders** behind one interface: the shared EmbeddingGemma 2 HTTP
  service (fast, GPU) and a local sentence-transformers CPU fallback (the model
  is already downloaded under /data/soffy/motionrag/hf).

Nothing here imports torch at module load: the local embedder is imported
lazily so the default (non-RAG) live path stays lightweight.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

DIM = 768  # EmbeddingGemma 2 native width
DEFAULT_ROOT = Path(os.environ.get("HEVI_MOTIONRAG_ROOT", "/data/soffy/motionrag"))
DEFAULT_INDEX = DEFAULT_ROOT / "index.npz"
DEFAULT_META = DEFAULT_ROOT / "index_meta.json"
DEFAULT_QUEUE = DEFAULT_ROOT / "gen_queue.jsonl"

# task prefixes (EmbeddingGemma 2 prompt templates)
PROMPT_QUERY = "task: search result | query: "
PROMPT_DOC = "title: none | text: "


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except Exception:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except Exception:
        return default


@dataclass
class Config:
    """Scoring / runtime knobs.  All overridable from the environment."""

    index: Path = field(
        default_factory=lambda: Path(os.environ.get("HEVI_MOTIONRAG_INDEX", DEFAULT_INDEX))
    )
    meta: Path = field(
        default_factory=lambda: Path(os.environ.get("HEVI_MOTIONRAG_META", DEFAULT_META))
    )
    queue: Path = field(
        default_factory=lambda: Path(os.environ.get("HEVI_MOTIONRAG_QUEUE", DEFAULT_QUEUE))
    )
    queries: Path = field(
        default_factory=lambda: Path(
            os.environ.get("HEVI_MOTIONRAG_QUERIES", str(DEFAULT_ROOT / "queries.npz"))
        )
    )
    # service
    emb_url: str = field(
        default_factory=lambda: os.environ.get(
            "HEVI_MOTIONRAG_EMB_URL", "http://100.68.226.13:8790"
        )
    )
    emb_mode: str = field(
        default_factory=lambda: os.environ.get("HEVI_MOTIONRAG_EMB", "auto")
    )  # auto|service|local
    local_model: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "HEVI_MOTIONRAG_LOCAL_MODEL",
                str(
                    DEFAULT_ROOT / "hf/hub/models--google--embeddinggemma-2/snapshots/"
                    "914f7f89142e33e77833254d9c9b90c3cef7303b"
                ),
            )
        )
    )
    hf_home: Path = field(
        default_factory=lambda: Path(
            os.environ.get("HEVI_MOTIONRAG_HF_HOME", str(DEFAULT_ROOT / "hf"))
        )
    )
    # stratum
    stratum_url: str = field(
        default_factory=lambda: os.environ.get("HEVI_MOTIONRAG_STRATUM_URL", "")
    )
    stratum_key: str = field(
        default_factory=lambda: os.environ.get("HEVI_MOTIONRAG_STRATUM_KEY", "")
    )
    owner: str = field(
        default_factory=lambda: os.environ.get("HEVI_MOTIONRAG_OWNER", "hevi-live/xiaoya_e")
    )
    # scoring weights
    w_text_video: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_W_TEXT_VIDEO", 0.5))
    w_text_text: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_W_TEXT_TEXT", 0.3))
    w_audio_video: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_W_AUDIO_VIDEO", 0.2))
    w_transition: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_W_TRANSITION", 0.15))
    w_repeat: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_W_REPEAT", 0.25))
    repeat_window_s: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_REPEAT_WINDOW", 10.0))
    miss_threshold: float = field(default_factory=lambda: _f("HEVI_MOTIONRAG_MISS_THRESHOLD", 0.55))
    # audio embedding on the hot path is ~3 s locally, ~fast on the service
    use_audio: str = field(
        default_factory=lambda: os.environ.get("HEVI_MOTIONRAG_AUDIO", "auto")
    )  # auto|1|0
    top_k_log: int = field(default_factory=lambda: _i("HEVI_MOTIONRAG_TOPK_LOG", 5))


# --------------------------------------------------------------------------
# embedders
# --------------------------------------------------------------------------


def _l2(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-9)


class Embedder:
    """Common interface: text / image / audio → L2-normalised (N,768) float32."""

    name = "base"

    def text(
        self, texts: Sequence[str], *, query: bool
    ) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def images(self, pil_images: Sequence) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    def audio(self, wav_paths: Sequence[Path]) -> np.ndarray | None:
        """Sentence-audio embedding.  Returns None when unsupported/too slow."""
        return None

    @property
    def audio_ok(self) -> bool:
        return False


class ServiceEmbedder(Embedder):
    """Client for the shared EmbeddingGemma 2 service (OpenAI-compatible).

    The local http proxy returns 502 for the tailnet address, so the client is
    built with ``trust_env=False`` (never reads http_proxy/https_proxy).
    """

    name = "service"

    def __init__(self, url: str, *, timeout: float = 60.0) -> None:
        import httpx

        self.base = url.rstrip("/")
        self.c = httpx.Client(base_url=self.base, timeout=timeout, trust_env=False)
        self._audio_ok: bool | None = None

    def text(self, texts: Sequence[str], *, query: bool) -> np.ndarray:
        body = {
            "input": list(texts),
            "model": "embeddinggemma-2",
            "dimensions": DIM,
            "task": "SearchQuery" if query else "Document",
        }
        r = self.c.post("/v1/embeddings", json=body)
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda d: d.get("index", 0))
        return _l2(np.asarray([d["embedding"] for d in data], dtype=np.float32))

    def images(self, pil_images: Sequence, *, chunk: int = 8) -> np.ndarray:
        import base64
        import io

        out: list[list[float]] = []
        for i in range(0, len(pil_images), chunk):
            items = []
            for im in pil_images[i : i + chunk]:
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=88)
                items.append({"image": base64.b64encode(buf.getvalue()).decode()})
            r = self.c.post("/v1/embeddings/multimodal", json={"input": items, "dimensions": DIM})
            r.raise_for_status()
            out.extend([d["embedding"] for d in r.json()["data"]])
        return _l2(np.asarray(out, dtype=np.float32))

    def audio(self, wav_paths: Sequence[Path]) -> np.ndarray | None:
        import base64

        out: list[list[float]] = []
        for p in wav_paths:
            b = base64.b64encode(Path(p).read_bytes()).decode()
            r = self.c.post(
                "/v1/embeddings/multimodal", json={"input": [{"audio": b}], "dimensions": DIM}
            )
            r.raise_for_status()
            out.extend([d["embedding"] for d in r.json()["data"]])
        self._audio_ok = True
        return _l2(np.asarray(out, dtype=np.float32))

    @property
    def audio_ok(self) -> bool:
        return bool(self._audio_ok)


class LocalEmbedder(Embedder):
    """sentence-transformers CPU fallback on the pre-downloaded local snapshot."""

    name = "local"

    def __init__(self, model_path: Path, *, allow_audio: bool = False) -> None:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault(
            "HF_HOME", str(Path(os.environ.get("HEVI_MOTIONRAG_HF_HOME", DEFAULT_ROOT / "hf")))
        )
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(_i("HEVI_MOTIONRAG_THREADS", max(1, (os.cpu_count() or 4) // 2)))
        self.m = SentenceTransformer(str(model_path), device="cpu")
        self._allow_audio = allow_audio

    def text(self, texts: Sequence[str], *, query: bool) -> np.ndarray:
        e = self.m.encode(
            list(texts),
            normalize_embeddings=True,
            batch_size=32,
            prompt=PROMPT_QUERY if query else PROMPT_DOC,
            show_progress_bar=False,
        )
        return _l2(np.asarray(e, dtype=np.float32))

    def images(self, pil_images: Sequence) -> np.ndarray:
        e = self.m.encode(
            list(pil_images), normalize_embeddings=True, batch_size=8, show_progress_bar=False
        )
        return _l2(np.asarray(e, dtype=np.float32))

    def audio(self, wav_paths: Sequence[Path]) -> np.ndarray | None:
        if not self._allow_audio:
            return None
        try:
            e = self.m.encode(
                [str(p) for p in wav_paths], normalize_embeddings=True, show_progress_bar=False
            )
        except Exception:
            return None
        return _l2(np.asarray(e, dtype=np.float32))

    @property
    def audio_ok(self) -> bool:
        return self._allow_audio


class QueryCache:
    """Precomputed per-utterance query vectors (text, audio, prosody).

    The offline renderer runs in the hevi venv, which has no sentence-transformers;
    the build venv (motionrag) computes the vectors once and saves them here, so
    the render path is pure numpy — no embedding, no network.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.text: dict[str, np.ndarray] = {}
        self.audio: dict[str, np.ndarray] = {}
        self.prosody: dict[str, dict] = {}

    @classmethod
    def load(cls, path: Path) -> "QueryCache":
        qc = cls(path)
        if not path.is_file():
            return qc
        z = np.load(path, allow_pickle=False)
        for k in z.files:
            if k.startswith("t_"):
                qc.text[k[2:]] = z[k]
            elif k.startswith("a_"):
                qc.audio[k[2:]] = z[k]
            elif k.startswith("p_"):
                qc.prosody[k[2:]] = json.loads(str(z[k]))
        return qc

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, np.ndarray] = {}
        for k, v in self.text.items():
            arrays[f"t_{k}"] = v
        for k, v in self.audio.items():
            arrays[f"a_{k}"] = v
        for k, v in self.prosody.items():
            arrays[f"p_{k}"] = np.array(json.dumps(v, ensure_ascii=False))
        np.savez_compressed(path, **arrays)

    @property
    def ok(self) -> bool:
        return bool(self.text)


def probe_service(url: str, *, timeout: float = 4.0) -> bool:
    """Cheap reachability check for the embedding service (never raises)."""
    try:
        import httpx

        with httpx.Client(timeout=timeout, trust_env=False) as c:
            r = c.post(
                url.rstrip("/") + "/v1/embeddings",
                json={"input": ["ping"], "dimensions": DIM},
            )
            return r.status_code == 200 and bool(r.json().get("data"))
    except Exception:
        return False


def get_embedder(cfg: Config, *, allow_audio: bool | None = None) -> Embedder:
    """Pick an embedder: service if requested/reachable, else local CPU.

    ``HEVI_MOTIONRAG_EMB`` = auto (default) | service | local.
    """
    want = cfg.emb_mode.lower()
    if want in ("service", "auto") and cfg.emb_url:
        if probe_service(cfg.emb_url):
            return ServiceEmbedder(cfg.emb_url)
        if want == "service":
            raise RuntimeError(f"HEVI_MOTIONRAG_EMB=service but {cfg.emb_url} is unreachable")
    audio = bool(allow_audio) if allow_audio is not None else cfg.use_audio == "1"
    return LocalEmbedder(cfg.local_model, allow_audio=audio)


def select_embedder(cfg: Config, *, allow_audio: bool | None = None) -> Embedder | None:
    """Like get_embedder but returns None if nothing is importable.

    The offline renderer runs in the hevi venv, which has no sentence-transformers;
    there, all query vectors must already be in the precomputed cache.
    """
    try:
        return get_embedder(cfg, allow_audio=allow_audio)
    except Exception:
        return None


# --------------------------------------------------------------------------
# prosody
# --------------------------------------------------------------------------


def _f0_track(
    wav: np.ndarray,
    sr: int,
    *,
    hop: int = 160,
    win: int = 512,
    fmin: float = 70.0,
    fmax: float = 400.0,
) -> np.ndarray:
    """Crude per-frame F0 (Hz) by autocorrelation; 0.0 where unvoiced."""
    n = 1 + max(0, (len(wav) - win) // hop)
    out = np.zeros(n, dtype=np.float32)
    lo, hi = int(sr / fmax), int(sr / fmin)
    for i in range(n):
        seg = wav[i * hop : i * hop + win].astype(np.float32)
        if len(seg) < win or np.sqrt(np.mean(seg * seg)) < 1e-3:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1 :]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lo2, hi2 = min(lo, len(ac) - 1), min(hi, len(ac) - 1)
        if hi2 <= lo2:
            continue
        k = lo2 + int(np.argmax(ac[lo2:hi2]))
        if ac[k] > 0.3:
            out[i] = sr / k
    return out


def prosody(wav: np.ndarray, sr: int, *, fps: float = 20.0, text: str = "") -> dict:
    """Cheap prosody summary used to steer motion.

    Returns ``rms`` (per output frame), ``stress_frac`` (where the loudest
    moment sits in the utterance), ``f0_lo``/``f0_hi`` (voiced pitch range),
    ``rate`` (chars per second) and ``energy`` (mean RMS).
    """
    if wav is None or len(wav) == 0:
        return {
            "rms": np.zeros(0, np.float32),
            "stress_frac": 0.5,
            "f0_lo": 0.0,
            "f0_hi": 0.0,
            "rate": 0.0,
            "energy": 0.0,
        }
    hop = max(1, int(sr / fps))
    n = max(1, len(wav) // hop)
    rms = np.array(
        [float(np.sqrt(np.mean(wav[i * hop : (i + 1) * hop] ** 2))) for i in range(n)], np.float32
    )
    # stress: loudest frame, but smoothed so a single click does not win
    if n >= 5:
        k = np.ones(5, np.float32) / 5
        sm = np.convolve(rms, k, mode="same")
    else:
        sm = rms
    stress_frac = float(int(np.argmax(sm)) / max(1, n - 1))
    f0 = _f0_track(wav, sr)
    voiced = f0[f0 > 0]
    dur = len(wav) / sr
    return {
        "rms": rms,
        "stress_frac": stress_frac,
        "f0_lo": float(np.percentile(voiced, 10)) if len(voiced) else 0.0,
        "f0_hi": float(np.percentile(voiced, 90)) if len(voiced) else 0.0,
        "rate": (len(text) / dur) if dur > 0 and text else 0.0,
        "energy": float(rms.mean()),
    }


def split_phrases(text: str) -> list[str]:
    """Split a sentence on Chinese clause punctuation into sub-phrases."""
    import re

    parts = [p for p in re.split(r"[，,、；;：:]+", text) if p.strip()]
    return parts or ([text] if text else [])


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------


@dataclass
class Seg:
    """One candidate motion segment (a slice of a clip)."""

    idx: int
    clip: str
    start: int  # frame index (inclusive)
    end: int  # frame index (exclusive)
    kinds: tuple[str, ...]  # subset of {"idle","talk"}
    text: str
    energy_peak: int  # frame offset within the clip of max motion energy
    video: np.ndarray  # (768,) mean of sampled-frame embeddings
    text_emb: np.ndarray  # (768,)
    pose_first: np.ndarray  # (P,)
    pose_last: np.ndarray  # (P,)

    @property
    def n_frames(self) -> int:
        return self.end - self.start


class LocalIndex:
    """npz-backed motion library.  This is the render-time store (no network)."""

    def __init__(self, segs: list[Seg], meta: dict) -> None:
        self.segs = segs
        self.meta = meta

    # -- persistence -----------------------------------------------------
    def save(self, path: Path, meta_path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            clip=np.array([s.clip for s in self.segs]),
            start=np.array([s.start for s in self.segs], np.int32),
            end=np.array([s.end for s in self.segs], np.int32),
            kinds=np.array(["|".join(s.kinds) for s in self.segs]),
            text=np.array([s.text for s in self.segs]),
            energy_peak=np.array([s.energy_peak for s in self.segs], np.int32),
            video=np.stack([s.video for s in self.segs]),
            text_emb=np.stack([s.text_emb for s in self.segs]),
            pose_first=np.stack([s.pose_first for s in self.segs]),
            pose_last=np.stack([s.pose_last for s in self.segs]),
        )
        meta_path.write_text(json.dumps(self.meta, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path, meta_path: Path | None = None) -> "LocalIndex":
        z = np.load(path, allow_pickle=False)
        meta = {}
        mp = meta_path or path.with_name("index_meta.json")
        if mp.is_file():
            meta = json.loads(mp.read_text())
        segs = [
            Seg(
                idx=i,
                clip=str(z["clip"][i]),
                start=int(z["start"][i]),
                end=int(z["end"][i]),
                kinds=tuple(str(z["kinds"][i]).split("|")),
                text=str(z["text"][i]),
                energy_peak=int(z["energy_peak"][i]),
                video=z["video"][i],
                text_emb=z["text_emb"][i],
                pose_first=z["pose_first"][i],
                pose_last=z["pose_last"][i],
            )
            for i in range(len(z["clip"]))
        ]
        return cls(segs, meta)

    @property
    def dim(self) -> int:
        return int(self.segs[0].video.shape[0]) if self.segs else DIM

    def clips(self) -> list[str]:
        return sorted({s.clip for s in self.segs})

    def candidates(self, kind: str) -> list[Seg]:
        return [s for s in self.segs if kind in s.kinds]


class StratumIndex:
    """Client for the AII/Stratum media-asset API (index-build time only).

    Implements the frozen contract in /data/soffy/motionrag/stratum_contract.md.
    Runtime retrieval never touches this — the local npz cache does.
    """

    def __init__(self, cfg: Config) -> None:
        import httpx

        if not cfg.stratum_url:
            raise RuntimeError("HEVI_MOTIONRAG_STRATUM_URL is not set")
        self.cfg = cfg
        headers = {"X-API-Key": cfg.stratum_key} if cfg.stratum_key else {}
        self.c = httpx.Client(
            base_url=cfg.stratum_url.rstrip("/"), headers=headers, timeout=120, trust_env=False
        )

    def _post(self, path: str, body: dict) -> dict:
        r = self.c.post(path, json=body)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "ok":
            raise RuntimeError(f"stratum error: {j.get('error')}")
        return j["data"]

    def push(
        self, assets: list[dict], links: list[dict] | None = None, *, embed_text: bool = False
    ) -> dict:
        return self._post(
            "/api/media/ingest",
            {
                "assets": assets,
                "links": links or [],
                "embed_text": embed_text,
                "embed_media": False,
            },
        )

    def search(self, **kw) -> list[dict]:
        body = {k: v for k, v in kw.items() if v is not None}
        return self._post("/api/media/search", body)["results"]

    def get(self, asset_id: str) -> dict:
        r = self.c.get(f"/api/media/{asset_id}")
        r.raise_for_status()
        return r.json()["data"]


# --------------------------------------------------------------------------
# retrieval
# --------------------------------------------------------------------------


@dataclass
class Choice:
    seg: Seg
    score: float
    parts: dict
    alternatives: list[tuple[str, float]] = field(default_factory=list)


class Retriever:
    """Scores motion segments against a (text, audio, pose) query."""

    def __init__(self, index: LocalIndex, cfg: Config) -> None:
        self.index = index
        self.cfg = cfg
        self.used: dict[str, float] = {}  # clip -> last time used (s)

    def score(
        self,
        q_text: np.ndarray | None,
        q_audio: np.ndarray | None,
        kind: str,
        cur_pose: np.ndarray | None,
        now: float,
    ) -> list[Choice]:
        cands = self.index.candidates(kind)
        out: list[Choice] = []
        for s in cands:
            st = float(q_text @ s.video) if q_text is not None else 0.0
            sd = float(q_text @ s.text_emb) if q_text is not None else 0.0
            sa = float(q_audio @ s.video) if q_audio is not None else 0.0
            trans = 0.0
            if cur_pose is not None:
                trans = float(np.linalg.norm(cur_pose - s.pose_first)) / (len(cur_pose) ** 0.5)
            rep = 0.0
            last = self.used.get(s.clip)
            if last is not None and (now - last) < self.cfg.repeat_window_s:
                rep = 1.0 - (now - last) / self.cfg.repeat_window_s
            sc = (
                self.cfg.w_text_video * st
                + self.cfg.w_text_text * sd
                + self.cfg.w_audio_video * sa
                - self.cfg.w_transition * trans
                - self.cfg.w_repeat * rep
            )
            out.append(
                Choice(
                    s,
                    sc,
                    {
                        "text_video": st,
                        "text_text": sd,
                        "audio_video": sa,
                        "transition": trans,
                        "repeat": rep,
                    },
                )
            )
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    def pick(self, q_text, q_audio, kind, cur_pose, now) -> Choice:
        ranked = self.score(q_text, q_audio, kind, cur_pose, now)
        best = ranked[0]
        best.alternatives = [(c.seg.clip, round(c.score, 3)) for c in ranked[: self.cfg.top_k_log]]
        self.used[best.seg.clip] = now
        return best


# --------------------------------------------------------------------------
# miss queue
# --------------------------------------------------------------------------


def log_miss(
    cfg: Config,
    *,
    text: str,
    audio: Path | None,
    duration: float,
    score: float,
    wanted: str,
    kind: str,
    clip: str,
) -> None:
    """Append a retrieval miss — a prompt for future Wan2.2 clip generation."""
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": text,
        "audio": str(audio) if audio else None,
        "duration_s": round(float(duration), 2),
        "best_score": round(float(score), 3),
        "threshold": cfg.miss_threshold,
        "wanted_description": wanted,
        "kind": kind,
        "chosen_clip": clip,
    }
    cfg.queue.parent.mkdir(parents=True, exist_ok=True)
    with cfg.queue.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# director
# --------------------------------------------------------------------------

XF = 8  # crossfade frames between clips (matches halfbody.Director)
IDLE_QUERY = (
    "安静地坐着等待，平静地看向镜头 idle, sitting still, waiting calmly, looking at the camera"
)


class RagDirector:
    """Drop-in replacement for halfbody.Director that retrieves motion.

    Same ``refs(kind, n, caption, wav)`` contract: it returns exactly ``n``
    frame refs — ``(clip, i)`` or a crossfade ``(clip, i, clip2, j, alpha)`` —
    so ``HalfBodyAvatar.frames`` can consume it unchanged.
    """

    def __init__(
        self,
        clips: dict,
        index: LocalIndex,
        embedder: Embedder | None,
        cfg: Config,
        *,
        fps: float = 20.0,
        sr: int = 16000,
        audio: bool = False,
        log_path: Path | None = None,
        queries: QueryCache | None = None,
    ) -> None:
        self.clips = clips
        self.index = index
        self.emb = embedder
        self.qc = queries or QueryCache()
        self.cfg = cfg
        self.fps = fps
        self.sr = sr
        self.use_audio = bool(audio) and (embedder is not None and embedder.audio_ok)
        self.retriever = Retriever(index, cfg)
        self.t = 0.0  # seconds of motion emitted so far
        self._last_pose = None
        self.audio_cache: dict[str, np.ndarray | None] = {}
        self.log_path = log_path
        self.choices: list[dict] = []
        self.misses = 0
        self._qtext_cache: dict[str, np.ndarray] = {}
        self._last_latency_ms = 0.0
        self._last_audio_path: str | None = None

    # -- query embeddings ------------------------------------------------
    def _q_text(self, text: str) -> np.ndarray:
        key = text.strip() or IDLE_QUERY
        if key in self._qtext_cache:
            return self._qtext_cache[key]
        t0 = time.perf_counter()
        if key in self.qc.text:  # precomputed (no embedding at render time)
            v = self.qc.text[key]
        elif self.emb is not None:
            v = self.emb.text([key], query=True)[0]
        else:
            raise RuntimeError(
                f"no embedder and no precomputed query for {key!r}; "
                "run scripts/precompute_queries.py first"
            )
        self._qtext_cache[key] = v
        self._last_latency_ms = (time.perf_counter() - t0) * 1000
        return v

    def _q_audio(self, wav: np.ndarray, key: str) -> np.ndarray | None:
        if wav is None or len(wav) == 0:
            return None
        if key in self.qc.audio:
            return self.qc.audio[key]
        if not self.use_audio or self.emb is None:
            return None
        if key not in self.audio_cache:
            import tempfile

            import soundfile as sf

            p = Path(tempfile.gettempdir()) / f"motionrag_{abs(hash(key)) % (10**9)}.wav"
            if not p.is_file():
                sf.write(str(p), wav, self.sr)
            try:
                self.audio_cache[key] = self.emb.audio([p])
            except Exception:
                self.audio_cache[key] = None
        e = self.audio_cache[key]
        return None if e is None else e[0]

    # -- planning --------------------------------------------------------
    def _blocks(self, kind: str, caption: str, wav) -> list[dict]:
        """Split the segment into sub-phrases, each with its own query.

        Each block carries ``stress`` = where the loudest moment sits *within
        that sub-phrase* (0..1), or None if unknown.  The gesture peak of the
        chosen segment is aligned to it.
        """
        if kind == "idle" or not caption:
            return [{"m": None, "text": IDLE_QUERY, "stress": None, "audio": None}]
        phrases = split_phrases(caption)
        if caption in self.qc.prosody:
            pros = self.qc.prosody[caption]
        else:
            pros = prosody(wav, self.sr, fps=self.fps, text=caption) if wav is not None else None
        q_audio = self._q_audio(wav, caption) if (wav is not None) else None
        total = sum(max(1, len(p)) for p in phrases)
        shares = [max(1, len(p)) / total for p in phrases]
        # character-share → normalized span of each phrase, for stress mapping
        spans, acc = [], 0.0
        for s in shares:
            spans.append((acc, acc + s))
            acc += s
        rms = pros.get("rms") if pros else None
        blocks = []
        for i, (p, s, (lo, hi)) in enumerate(zip(phrases, shares, spans)):
            stress = None
            if rms is not None and len(rms) > 0:
                a, b = int(lo * len(rms)), max(int(lo * len(rms)) + 1, int(hi * len(rms)))
                seg = rms[a:b]
                if len(seg) >= 3:
                    seg = np.convolve(seg, np.ones(3, np.float32) / 3, mode="same")
                stress = float(int(np.argmax(seg)) / max(1, len(seg) - 1)) if len(seg) else None
            elif pros is not None:
                sf = pros["stress_frac"]
                if lo <= sf < hi or (i == len(phrases) - 1 and sf >= lo):
                    stress = (sf - lo) / max(1e-6, hi - lo)
            blocks.append({"m": None, "text": p, "share": s, "stress": stress, "audio": q_audio})
        return blocks

    def _plan_block(
        self, kind: str, m: int, q_text: np.ndarray, q_audio, stress, text: str, audio_path
    ) -> list[tuple]:
        """Greedily fill ``m`` frames from retrieved segments, returning actions."""
        actions: list[tuple] = []
        remaining = m
        first = True
        guard = 0
        while remaining > 0 and guard < 64:
            guard += 1
            ch = self.retriever.pick(q_text, q_audio, kind, self._last_pose, self.t)
            seg = ch.seg
            clip = self.clips[seg.clip]
            n = seg.end - seg.start
            # time-warp: play the whole segment, stretched or squeezed by <=20%
            stride = min(1.2, max(0.8, n / max(1, remaining)))
            usable = max(1, int((n - 1) / stride)) if n > 1 else 1
            take = min(remaining, usable)
            start = seg.start
            # align the segment's motion-energy peak with the phrase's stress
            if first and stress is not None and seg.start < seg.energy_peak < seg.end:
                want = max(1, int(round(stress * take)))
                lo = seg.start
                hi = max(seg.start, seg.end - 1 - take * stride)
                start = min(max(lo, seg.energy_peak - want * stride), hi)
            actions.append((clip, seg, start, stride, take))
            remaining -= take
            first = False
            self._last_pose = seg.pose_last
            self.choices.append(
                {
                    "kind": kind,
                    "text": text,
                    "clip": seg.clip,
                    "seg": [seg.start, seg.end],
                    "score": round(ch.score, 4),
                    "parts": {k: round(v, 4) for k, v in ch.parts.items()},
                    "top": ch.alternatives,
                    "stride": round(stride, 3),
                    "latency_ms": round(self._last_latency_ms, 1),
                }
            )
            if ch.score < self.cfg.miss_threshold:
                self.misses += 1
                log_miss(
                    self.cfg,
                    text=text,
                    audio=Path(audio_path) if audio_path else None,
                    duration=m / self.fps,
                    score=ch.score,
                    wanted=seg.text,
                    kind=kind,
                    clip=seg.clip,
                )
        return actions

    def _assemble(self, actions: list[tuple], n: int) -> list[tuple]:
        out: list[tuple] = []
        prev = None
        for clip, seg, start, stride, take in actions:
            if prev is not None:
                pc, pi = prev
                for j in range(XF):
                    jj = min(int(round(start + j)), len(clip) - 1)
                    out.append((pc, pi, clip, jj, (j + 1) / (XF + 1)))
                start = min(int(round(start + XF * stride)), len(clip) - 1)
                take = max(0, take - XF)
            for k in range(take):
                idx = min(int(round(start + k * stride)), len(clip) - 1)
                out.append((clip, idx))
            end_idx = min(int(round(start + max(0, take - 1) * stride)), len(clip) - 1)
            prev = (clip, end_idx)
        if len(out) < n:
            last = out[-1] if out else (next(iter(self.clips.values())), 0)
            base = (last[0], last[1])
            out.extend([base] * (n - len(out)))
        return out[:n]

    def refs(self, kind: str, n: int, caption: str = "", wav=None, audio_path=None) -> list[tuple]:
        self._last_audio_path = str(audio_path) if audio_path else None
        blocks = self._blocks(kind, caption, wav)
        actions: list[tuple] = []
        if kind == "idle" or not caption:
            q = self._q_text(IDLE_QUERY)
            actions = self._plan_block("idle", n, q, None, None, IDLE_QUERY, None)
        else:
            # allocate frames per sub-phrase by character share
            alloc = [max(1, int(round(b["share"] * n))) for b in blocks]
            alloc[-1] = max(1, n - sum(alloc[:-1])) if len(alloc) > 1 else n
            alloc[-1] += n - sum(alloc)
            for b, m in zip(blocks, alloc):
                if m <= 0:
                    continue
                q = self._q_text(b["text"])
                actions += self._plan_block(
                    kind, m, q, b["audio"], b["stress"], b["text"], self._last_audio_path
                )
        refs = self._assemble(actions, n)
        self.t += n / self.fps
        return refs

    def dump_choices(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.choices, ensure_ascii=False, indent=2))


def build_rag_director(
    avatar: str, *, yolo, clips: dict | None = None, fps: float = 20.0, sr: int = 16000
) -> RagDirector | None:
    """Construct a RagDirector for ``avatar``, or None if no index is present."""
    cfg = Config()
    if not cfg.index.is_file():
        return None
    index = LocalIndex.load(cfg.index, cfg.meta)
    emb = select_embedder(cfg, allow_audio=cfg.use_audio == "1")
    qc = QueryCache.load(cfg.queries)
    if emb is None and not qc.ok:
        return None  # no way to build query vectors — fall back to the random director
    if clips is None:
        from hevi.live_host.avatar.halfbody import load_library

        clips = load_library(avatar, yolo=yolo)
    have = {s.clip for s in index.segs}
    clips = {k: v for k, v in clips.items() if k in have}
    if len(clips) < 2:
        return None
    audio = bool(qc.audio) or (
        emb is not None and (cfg.use_audio == "1" or (cfg.use_audio == "auto" and emb.audio_ok))
    )
    log_path = (
        Path(os.environ.get("HEVI_MOTIONRAG_CHOICES", ""))
        if os.environ.get("HEVI_MOTIONRAG_CHOICES")
        else None
    )
    return RagDirector(
        clips, index, emb, cfg, fps=fps, sr=sr, audio=audio, log_path=log_path, queries=qc
    )
