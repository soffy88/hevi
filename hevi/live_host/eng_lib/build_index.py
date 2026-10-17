"""Build (or rebuild) the EG2 index.npz for an already-generated eng_lib unit.

The generation step (build_unit.py) runs under the CosyVoice venv, which has no
httpx and therefore cannot reach the EmbeddingGemma 2 service — its in-process
index build is skipped by design.  This script does that half with an
interpreter that has the deps, reading whatever build_unit.py already wrote:

    /data/soffy/englib/<book>/<unit>/{manifest.json, wav/}  ->  index.npz

Run from the hevi venv:

    PYTHONPATH=/data/soffy/projects/hevi-live \\
    /data/soffy/projects/hevi/.venv/bin/python \\
        hevi/live_host/eng_lib/build_index.py --unit /data/soffy/englib/pep-g7a/u1

Idempotent; safe to re-run after adding items.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default="/data/soffy/englib/pep-g7a/u1")
    ap.add_argument(
        "--query-check",
        action="store_true",
        help="also report the nearest-neighbour of a few probe phrases",
    )
    args = ap.parse_args()
    root = Path(args.unit)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    items = [i for i in manifest["items"] if (root / i["wav"]).is_file()]
    if not items:
        raise SystemExit(f"no generated items under {root}")

    from hevi.live_host.avatar.motionrag import Config, get_embedder

    emb = get_embedder(Config(), allow_audio=False)
    vecs = emb.text([i["text"] for i in items], query=False)
    np.savez_compressed(root / "index.npz", ids=np.array([i["id"] for i in items]), text=vecs)
    print(f"index.npz written: {vecs.shape} for {len(items)} items", flush=True)

    if args.query_check:
        probes = [
            "hello",
            "nice to meet you",
            "good morning",
            "what is your name",
            "spell your name",
            "thank you",
            "I am fine",
        ]
        for p in probes:
            qv = emb.text([p], query=True)[0]
            sims = vecs @ qv
            j = int(np.argmax(sims))
            print(
                f"  probe {p!r:22s} -> {items[j]['id']} "
                f"'{items[j]['text'][:30]}' cos={float(sims[j]):.3f}",
                flush=True,
            )


if __name__ == "__main__":
    main()
