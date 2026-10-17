#!/usr/bin/env python
"""Precompute motion-RAG query vectors for a script (run in the motionrag venv).

The offline renderer (hevi venv) has no sentence-transformers, so every query
vector a sentence needs — its text embedding, its audio embedding and its
prosody summary — is computed here once and saved to an npz the renderer loads
(`QueryCache`).  The render path is then pure numpy: no embedding, no network.

    PYTHONPATH=. /data/soffy/motionrag/.venv/bin/python \
        scripts/precompute_motion_queries.py \
        --sents /data/soffy/cosyvoice/reading/huozhe.json \
        --wav-dir /data/soffy/cosyvoice/reading/huozhe \
        --out /data/soffy/motionrag/queries.npz
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "motionrag", ROOT / "hevi/live_host/avatar/motionrag.py"
)
_mr = importlib.util.module_from_spec(_spec)
sys.modules["motionrag"] = _mr
_spec.loader.exec_module(_mr)

Config, QueryCache, get_embedder, prosody, split_phrases = (
    _mr.Config,
    _mr.QueryCache,
    _mr.get_embedder,
    _mr.prosody,
    _mr.split_phrases,
)


def _load_wav(path: Path, sr: int) -> np.ndarray:
    import subprocess

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sents", type=Path, default=Path("/data/soffy/cosyvoice/reading/huozhe.json"))
    ap.add_argument("--wav-dir", type=Path, default=Path("/data/soffy/cosyvoice/reading/huozhe"))
    ap.add_argument("--out", type=Path, default=Config().queries)
    ap.add_argument("--audio", action="store_true", help="also embed each sentence wav")
    ap.add_argument("--fps", type=float, default=20.0)
    ap.add_argument("--sr", type=int, default=16000)
    args = ap.parse_args()
    cfg = Config()

    sents = json.loads(args.sents.read_text())
    emb = get_embedder(cfg, allow_audio=args.audio)
    qc = QueryCache(args.out)

    # text queries: the idle phrase, every sentence, and every sub-phrase
    texts = [_mr.IDLE_QUERY]
    for s in sents:
        texts.append(s)
        texts.extend(split_phrases(s))
    texts = list(dict.fromkeys(t.strip() for t in texts if t.strip()))
    t0 = time.time()
    vecs = emb.text(texts, query=True)
    print(
        f"[precompute] {len(texts)} text queries in {time.time() - t0:.1f}s (embedder={emb.name})"
    )
    for t, v in zip(texts, vecs):
        qc.text[t] = v.astype(np.float32)

    # prosody (local, cheap) + audio embedding per sentence
    for i, s in enumerate(sents):
        wav = _load_wav(args.wav_dir / f"s{i:02d}.wav", args.sr)
        p = prosody(wav, args.sr, fps=args.fps, text=s)
        qc.prosody[s] = {
            "stress_frac": p["stress_frac"],
            "f0_lo": p["f0_lo"],
            "f0_hi": p["f0_hi"],
            "rate": p["rate"],
            "energy": p["energy"],
        }
        if args.audio:
            try:
                a = emb.audio([args.wav_dir / f"s{i:02d}.wav"])
                if a is not None:
                    qc.audio[s] = a[0]
            except Exception as e:  # noqa: BLE001
                print(f"[precompute] audio embed failed for s{i:02d}: {type(e).__name__}")
        print(
            f"[precompute] s{i:02d} prosody stress={p['stress_frac']:.2f} "
            f"f0={p['f0_lo']:.0f}-{p['f0_hi']:.0f}Hz rate={p['rate']:.1f}c/s",
            flush=True,
        )

    qc.save(args.out)
    print(
        f"[precompute] wrote {args.out}: {len(qc.text)} text, {len(qc.audio)} audio, "
        f"{len(qc.prosody)} prosody"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
