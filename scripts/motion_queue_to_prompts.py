#!/usr/bin/env python
"""Turn the motion-RAG miss queue into Wan2.2 clip-generation prompts.

Every retrieval miss (`/data/soffy/motionrag/gen_queue.jsonl`, written by
`motionrag.log_miss`) records what the avatar was saying, how long the phrase
lasted and which clip was the least-bad fallback.  Deduplicated by wanted
description, these become prompts for future gesture clips (rendered on Colab
with Wan2.2, then dropped into assets/halfbody/ and re-indexed).

    python scripts/motion_queue_to_prompts.py                       # print
    python scripts/motion_queue_to_prompts.py --out prompts.jsonl   # write
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT_QUEUE = Path("/data/soffy/motionrag/gen_queue.jsonl")

STYLE = (
    "half-body shot of a young Chinese woman host, sitting at a desk, "
    "warm indoor lighting, static camera, 480x864 portrait, 5 s, 20 fps, "
    "silent (no audio), smooth natural motion, no text"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--min-count", type=int, default=1)
    args = ap.parse_args()
    if not args.queue.is_file():
        print(f"no queue at {args.queue}")
        return 0

    rows = [
        json.loads(line)
        for line in args.queue.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_desc: dict[str, list[dict]] = {}
    for r in rows:
        by_desc.setdefault(r["wanted_description"], []).append(r)

    prompts = []
    for desc, hits in sorted(by_desc.items(), key=lambda kv: -len(kv[1])):
        if len(hits) < args.min_count:
            continue
        examples = [h["text"] for h in hits[:5]]
        dur = max(h["duration_s"] for h in hits)
        prompts.append(
            {
                "clip_id": f"gen_{abs(hash(desc)) % 100000:05d}",
                "prompt": f"{desc}. {STYLE}",
                "wanted_description": desc,
                "hits": len(hits),
                "target_duration_s": round(min(5.0, max(1.5, dur)), 2),
                "example_lines": examples,
                "worst_score": round(min(h["best_score"] for h in hits), 3),
            }
        )
    prompts.sort(key=lambda p: -p["hits"])
    print(f"{len(rows)} misses → {len(prompts)} unique prompts")
    for p in prompts[:20]:
        print(f"  [{p['hits']:3d}×  score≤{p['worst_score']}] {p['prompt'][:110]}")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in prompts), encoding="utf-8"
        )
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
