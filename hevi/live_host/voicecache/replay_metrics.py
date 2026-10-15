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

# The ollama client uses httpx with the proxy env enabled (unlike the EG2 client,
# which sets trust_env=False).  A caller that OVERWRITES no_proxy to reach the
# EG2 tailnet host (e.g. NO_PROXY=100.68.226.13) drops localhost from the exempt
# list, so http://localhost:11434 gets sent through the http proxy and every
# reply comes back empty.  Keep localhost exempt regardless of the caller.
for _k in ("no_proxy", "NO_PROXY"):
    _parts = [p.strip() for p in os.environ.get(_k, "").split(",") if p.strip()]
    for _host in ("localhost", "127.0.0.1", "::1"):
        if _host not in _parts:
            _parts.append(_host)
    os.environ[_k] = ",".join(_parts)

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


def _make_embedder():
    """EG2 embedder for the query side of the cosine match.  Offline only — the
    live path never embeds (it is exact/normalised only)."""
    try:
        from hevi.live_host.avatar.motionrag import Config, get_embedder

        return get_embedder(Config(), allow_audio=False)
    except Exception as e:
        print("no query embedder (exact/normalised matching only):", e, flush=True)
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="/data/soffy/voicecache")
    ap.add_argument("--danmaku", default="/data/soffy/voicecache/test_danmaku.json")
    ap.add_argument("--out", default="/data/soffy/voicecache/REPORT_metrics.json")
    ap.add_argument("--max-prompts", type=int, default=50)
    ap.add_argument("--no-llm", action="store_true", help="use recorded replies only (offline)")
    args = ap.parse_args()

    cache = VoiceCache(root=Path(args.cache), embedder=_make_embedder())
    print(
        f"cache ready={cache.ready} entries={len(cache.entries)} threshold={cache.threshold} "
        f"cosine_path={'on' if cache._emb is not None and cache._text_matrix is not None else 'off'}",
        flush=True,
    )
    if cache._text_matrix is not None and cache._emb is None:
        print(
            "WARNING: index has text vectors but no query embedder — cosine "
            "matching disabled, only exact/normalised hits will count.",
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
    empty_replies = 0
    llm_errors = 0
    # every (sentence, best entry, score) so thresholds can be swept afterwards
    scored: list[dict] = []
    t0_all = time.time()

    for i, q in enumerate(danmaku):
        if args.no_llm:
            reply = ""
        else:
            try:
                reply = llm.reply(q)
            except Exception as e:  # noqa: BLE001 - a transient ollama hiccup must not read as a miss
                llm_errors += 1
                print(f"  LLM ERROR on {q!r}: {type(e).__name__}: {e}", flush=True)
                reply = ""
            if not reply.strip():
                empty_replies += 1
        for s in split_sentences(reply):
            total_sentences += 1
            entry, score = cache.match(s)
            scored.append(
                {
                    "sentence": s,
                    "entry_id": entry.id if entry is not None else None,
                    "category": entry.category if entry is not None else None,
                    "score": round(float(score), 4),
                    "exact": score >= 0.999,
                }
            )
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

    # A broken LLM path (ollama down / model missing / transient error) used to
    # surface as a flat 0.0 hit rate over 0 sentences — indistinguishable from a
    # genuinely bad cache.  Refuse to write metrics in that case.
    if not args.no_llm and empty_replies > len(danmaku) * 0.5:
        print(
            f"ABORT: {empty_replies}/{len(danmaku)} prompts got an empty reply "
            f"({llm_errors} raised). Is ollama up and the v2 model pulled? "
            f"Not writing metrics.",
            flush=True,
        )
        raise SystemExit(2)

    hit_rate = hits / total_sentences if total_sentences else 0.0
    # threshold sweep: how the hit rate and saved latency move as the cutoff
    # slides.  EG2 cosines for same-intent paraphrases cluster ~0.76-0.9 while
    # unrelated lines sit ~0.66-0.76, so the default 0.82 is not obviously right.
    sweep = []
    for th in (0.70, 0.72, 0.74, 0.76, 0.78, 0.80, 0.82, 0.85, 0.88):
        h = sum(1 for r in scored if r["entry_id"] and r["score"] >= th)
        sweep.append(
            {
                "threshold": th,
                "hit_rate": round(h / total_sentences, 4) if total_sentences else 0.0,
                "n_hits": h,
            }
        )
    metrics = {
        "n_prompts": len(danmaku),
        "n_sentences": total_sentences,
        "n_hits": hits,
        "hit_rate": round(hit_rate, 4),
        "n_misses": total_sentences - hits,
        "n_empty_replies": empty_replies,
        "n_llm_errors": llm_errors,
        "piper_time_saved_s": round(piper_saved, 2),
        "cosyvoice_equiv_saved_s": round(cosy_saved, 2),
        "threshold_sweep": sweep,
        "avg_latency_saved_per_hit_s": round(piper_saved / hits, 3) if hits else 0.0,
        "cache_entries": len(cache.entries),
        "threshold": cache.threshold,
        "model": "xiaoya-qwen3-4b-v2",
        "wall_s": round(time.time() - t0_all, 1),
        "top_misses": [{"text": t, "norm": normalize(t)} for t in miss_texts[:40]],
        "per_category_hit_rate": {c: round(sum(v) / len(v), 3) for c, v in per_cat_hits.items()},
        "scored": scored,
    }
    Path(args.out).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    print("METRICS DONE", flush=True)


if __name__ == "__main__":
    main()
