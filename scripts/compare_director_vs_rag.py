#!/usr/bin/env python
"""How many distinct motion segments the Director vs. motion-RAG use for 《活着》.

The render needs ~8 GB and keeps getting OOM-killed on this shared host, so the
question "how varied is the motion?" is answered analytically instead: the
Director is deterministic given its seed (7) and its `refs()` needs no pixels,
so its frame plan is replayed by frame *names* alone.  RAG is read from the
renderer's own `rag_choices.json`.

    PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/python \
        scripts/compare_director_vs_rag.py

Writes audit/live_host/reading/director_vs_rag.json.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hevi.live_host.avatar.halfbody import (  # noqa: E402
    FPS,
    SR,
    Director,
    Segment,
    load_wav16k,
)
from hevi.live_host.avatar.motionrag import LocalIndex  # noqa: E402

WAV_DIR = Path("/data/soffy/cosyvoice/reading/huozhe")
SENTS = json.loads(Path("/data/soffy/cosyvoice/reading/huozhe.json").read_text())
STATE = Path("/data/soffy/motionrag")
OUT = ROOT / "audit/live_host/reading/director_vs_rag.json"


def script_segments() -> list[Segment]:
    """Mirror render_reading.py's segment layout exactly."""
    segs = [Segment("idle", int(1.0 * FPS), caption="小雅读书｜《活着》")]
    for i, s in enumerate(SENTS):
        w = load_wav16k(WAV_DIR / f"s{i:02d}.wav")
        w = np.concatenate([w, np.zeros(int(0.35 * SR), dtype=np.float32)])
        segs.append(Segment("talk", max(1, round(len(w) / SR * FPS)), w=w, caption=s))
    segs.append(Segment("idle", int(1.5 * FPS), caption="小雅读书｜《活着》"))
    return segs


def main() -> int:
    index = LocalIndex.load(STATE / "index.npz", STATE / "index_meta.json")
    nframes = {c: 0 for c in index.meta["clips"]}
    for s in index.segs:  # start/end are clip-frame coordinates
        nframes[s.clip] = max(nframes[s.clip], int(s.end))
    print(f"[cmp] index: {len(index.segs)} segments, clip lengths={nframes}", flush=True)

    # --- Director replay (deterministic seed=7; only clip lengths matter) ---
    class _Clip:
        __slots__ = ("n",)

        def __init__(self, n: int) -> None:
            self.n = n

        def __len__(self) -> int:
            return self.n

    d = Director({k: _Clip(n) for k, n in nframes.items()})
    segs = script_segments()
    dir_frames: list[str] = []
    for sg in segs:
        for r in d.refs(sg.kind, sg.n_frames, sg.caption):
            dir_frames.append(r[0])

    # contiguous runs in one clip == one played-out segment
    dir_segs: Counter = Counter()
    prev = None
    for clip in dir_frames:
        if clip != prev:
            dir_segs[clip] += 1
            prev = clip

    # --- RAG: every choice the renderer logged ------------------------------
    choices = json.loads((ROOT / "audit/live_host/reading/rag_choices.json").read_text())
    rag_clip: Counter = Counter(c["clip"] for c in choices if c.get("clip"))
    rag_segs = {(c["clip"], tuple(c["seg"])) for c in choices if c.get("clip")}
    scores = [c["score"] for c in choices if c.get("clip")]

    report = {
        "index_segments": len(index.segs),
        "rag": {
            "choices": len(choices),
            "distinct_segments": len(rag_segs),
            "distinct_clips": len(rag_clip),
            "frames_by_clip": dict(rag_clip),
            "score_mean": round(sum(scores) / len(scores), 4),
            "score_min": round(min(scores), 4),
            "score_max": round(max(scores), 4),
        },
        "director": {
            "frames": len(dir_frames),
            "distinct_segments": sum(dir_segs.values()),
            "distinct_clips": len(dir_segs),
            "frames_by_clip": dict(dir_segs),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[cmp] RAG      {report['rag']}", flush=True)
    print(f"[cmp] Director {report['director']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
