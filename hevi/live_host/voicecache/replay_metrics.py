"""Part A metrics: replay typical danmaku through the v2 host model and measure
the voice-cache hit rate + latency saved.

This is a STANDALONE script (slow: needs ollama + Piper).  It does NOT touch the
running live service and does NOT change any default model.

What it does
------------
1. Load 50 typical danmaku (test_danmaku.json).
2. For each, get the v2 reply via OllamaLLM(xiaoya-qwen3-4b-v2) — the SAME model
   and system prompt the live host uses.
3. Split the reply into sentences exactly like skill_think._split_sentences.
4. Look every sentence up in the voice cache (exact/normalized + EG2 cosine).
5. Measure the live TTS time that a hit would have skipped (Piper, the live
   engine) and the CosyVoice-equivalent (RTF ~ measured) for reporting.
6. Write metrics to REPORT.json and print a summary.

Usage:
    python hevi/live_host/voicecache/replay_metrics.py \
        --cache /data/soffy/voicecache \
        --danmaku /data/soffy/voicecache/test_danmaku.json \
        --out /data/soffy/voicecache/REPORT_metrics.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

os.environ.setdefault("HEVI_VOICECACHE_ROOT", "/data/soffy/voicecache")

from hevi.live_host.voicecache import VoiceCache, normalize  # noqa: E402
from hevi.live_host.oprim.llm_ollama import OllamaLLM  # noqa: E402
from hevi.live_host.schemas import EngineConfig  # noqa: E402


def split_sentences(text: str) -> list[str]:
    """Mirror oskill.skill_think._split_sentences (the live reply->utterance split)."""
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?；;．·\n" and buf.strip():
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/data/soffy/voicecache")
    ap.add_argument("--danmaku", default="/data/soffy/voicecache/test_danmaku.json")
    ap.add_argument("--out", default="/data/soffy/voicecache/REPORT_metrics.json")
    ap.add_argument("--max-prompts", type=int, default=50)
    ap.add_argument("--no-llm", action="store_true", help="use recorded replies only (offline)")
    args = ap.parse_args()

    cache = VoiceCache(root=Path(args.cache))
    print(
        f"cache ready={cache.ready} entries={len(cache.entries)} threshold={cache.threshold}",
        flush=True,
    )

    danmaku = json.loads(Path(args.danmaku).read_text(encoding="utf-8"))["danmaku"][
        : args.max_prompts
    ]
    print(f"danmaku: {len(danmaku)} prompts", flush=True)

    # v2 model + persona identical to the live host
    cfg = EngineConfig()
    llm = OllamaLLM(
        base_url=cfg.ollama_base_url,
        model="xiaoya-qwen3-4b-v2",
        persona=cfg.persona,
        max_reply_chars=60,
    )

    # optional live-TTS clock (Piper is the live engine)
    try:
        from hevi.live_host.oprim.tts_piper import PiperTTS

        piper = PiperTTS()
        piper_ok = True
    except Exception:
        piper_ok = False
        piper = None

    # measured CosyVoice RTF (from gen smoke test) for the equivalent-savings line
    cosy_rtf = 8.5

    total_sentences = 0
    hits = 0
    miss_texts: list[str] = []
    piper_saved = 0.0
    cosy_saved = 0.0
    per_cat_hits: dict[str, list[bool]] = {}
    t0_all = time.time()

    for i, q in enumerate(danmaku):
        if args.no_llm:
            reply = ""
        else:
            reply = llm.reply(q)
        for s in split_sentences(reply):
            total_sentences += 1
            entry, score = cache.match(s)
            is_hit = entry is not None and score >= cache.threshold
            if is_hit:
                hits += 1
                cat = entry.category
                per_cat_hits.setdefault(cat, []).append(True)
                # latency that this hit would have skipped
                if piper_ok:
                    t0 = time.perf_counter()
                    try:
                        import tempfile

                        p = Path(tempfile.mkdtemp()) / "s.wav"
                        piper.synthesize(s, p)
                        piper_saved += time.perf_counter() - t0
                    except Exception:
                        pass
                dur = entry.duration or 2.0
                cosy_saved += dur * cosy_rtf
            else:
                miss_texts.append(s)
                # record which category bucket it would belong to (none)
        if (i + 1) % 10 == 0:
            print(
                f"  prompt {i + 1}/{len(danmaku)} sentences={total_sentences} hits={hits}",
                flush=True,
            )

    hit_rate = hits / total_sentences if total_sentences else 0.0
    metrics = {
        "n_prompts": len(danmaku),
        "n_sentences": total_sentences,
        "n_hits": hits,
        "hit_rate": round(hit_rate, 4),
        "n_misses": total_sentences - hits,
        "piper_time_saved_s": round(piper_saved, 2),
        "cosyvoice_equiv_saved_s": round(cosy_saved, 2),
        "avg_latency_saved_per_hit_s": round(piper_saved / hits, 3) if hits else 0.0,
        "cache_entries": len(cache.entries),
        "threshold": cache.threshold,
        "model": "xiaoya-qwen3-4b-v2",
        "wall_s": round(time.time() - t0_all, 1),
        "top_misses": [{"text": t, "norm": normalize(t)} for t in miss_texts[:40]],
        "per_category_hit_rate": {c: round(sum(v) / len(v), 3) for c, v in per_cat_hits.items()},
    }
    Path(args.out).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    print("METRICS DONE", flush=True)


if __name__ == "__main__":
    main()
