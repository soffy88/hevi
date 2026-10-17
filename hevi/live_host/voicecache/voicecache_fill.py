"""Batch-fill the voice cache from runtime misses.

The live path (HEVI_LIVE_VOICECACHE=on) logs every miss to miss_queue.jsonl.
This script drains that queue, generates a wav per miss with the same CosyVoice3
female voice, appends the new entries to the library, re-embeds (EG2) and rewrites
manifest.json + index.npz.  Idempotent: already-cached normalised texts are
skipped.

Run with the CosyVoice venv:

    TMPDIR=/data/soffy/voicecache/tmp \\
    /data/soffy/cosyvoice/venv/bin/python \\
        hevi/live_host/voicecache/voicecache_fill.py [--root /data/soffy/voicecache]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

COSY_DIR = "/data/soffy/cosyvoice/CosyVoice"
MODEL_DIR = "/data/soffy/cosyvoice/models/Fun-CosyVoice3-0.5B"
PROMPT_WAV = "./asset/zero_shot_prompt.wav"
PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"

DEFAULT_ROOT = Path(os.environ.get("HEVI_VOICECACHE_ROOT", "/data/soffy/voicecache"))


def _slug(text: str) -> str:
    s = re.sub(r"[^\w一-鿿]+", "_", text)
    return f"miss_{s[:28]}"


# must stay identical to hevi.live_host.voicecache.normalize (kept in sync by
# tests/test_voicecache.py::test_fill_normalize_matches_library)
_PUNCT = re.compile(r"[\s，,。.！!？?；;：:、~～…—\-_“”\"'‘’（）()\[\]【】<>《》/\\|]+")
_WRAP = re.compile(r"^[【\[].*?[】\]]")


def _normalize(text: str) -> str:
    t = text or ""
    t = _WRAP.sub("", t)
    t = _PUNCT.sub(" ", t)
    t = t.lower().strip()
    return re.sub(r"\s+", "", t)


# miss text → halfbody motion clip hint (kept small: the library already carries
# the main categories; a filled miss just needs a reasonable gesture)
_MOTION_CUES = (
    ("谢谢", "g_heart"),
    ("感谢", "g_heart"),
    ("比心", "g_heart"),
    ("抱抱", "g_heart"),
    ("欢迎", "g_wave"),
    ("哈喽", "g_wave"),
    ("你好", "g_wave"),
    ("关注", "g_nod"),
    ("点赞", "g_nod"),
    ("晚安", "g_wave"),
    ("拜拜", "g_wave"),
    ("再见", "g_wave"),
)


def _motion_hint(text: str) -> str:
    for k, m in _MOTION_CUES:
        if k in text:
            return m
    return "talk_a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--limit", type=int, default=0, help="max misses to fill (0=all)")
    ap.add_argument("--dry", action="store_true", help="only count, do not generate")
    args = ap.parse_args()
    root = Path(args.root)
    queue = root / "miss_queue.jsonl"
    manifest_path = root / "manifest.json"
    wav_dir = root / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    if not queue.is_file():
        print("no miss queue; nothing to fill", flush=True)
        return

    # load existing library
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.is_file()
        else {"entries": []}
    )
    # dedup on the NORMALISED text (the same key the live matcher uses), so a
    # miss that only differs in punctuation from a cached line is skipped.
    # NOTE: local copy of VoiceCache.normalize — this script runs under the
    # CosyVoice venv, which has no hevi deps (no httpx), so we don't import it.
    existing_norm = {_normalize(e["text"]) for e in manifest["entries"]}

    # collect unique misses (newest last), dedupe by normalised text
    seen: dict[str, str] = {}
    for line in queue.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        t = rec.get("text", "").strip()
        if t:
            seen[t] = rec.get("ts", "")

    to_fill = [t for t in seen if _normalize(t) not in existing_norm]
    if args.limit:
        to_fill = to_fill[: args.limit]
    print(f"misses unique={len(seen)} new={len(to_fill)} existing={len(existing_norm)}", flush=True)
    if args.dry or not to_fill:
        return

    os.chdir(COSY_DIR)
    sys.path += [".", "third_party/Matcha-TTS"]
    import torch
    import torchaudio

    torch.set_num_threads(int(os.environ.get("HEVI_LIVE_THREADS", "8")))
    from cosyvoice.cli.cosyvoice import AutoModel

    m = AutoModel(model_dir=MODEL_DIR)
    sr = m.sample_rate

    new_entries = []
    for text in to_fill:
        eid = _slug(text)
        out = wav_dir / f"{eid}.wav"
        if out.exists() and out.stat().st_size > 0:
            dur = _duration(out)
        else:
            t0 = time.time()
            w = torch.cat(
                [
                    j["tts_speech"]
                    for j in m.inference_zero_shot(text, PROMPT_TEXT, PROMPT_WAV, stream=False)
                ],
                1,
            )
            torchaudio.save(str(out), w, sr)
            dur = w.shape[1] / sr
            print(f"{eid} '{text[:16]}' dur={dur:.2f}s gen={time.time() - t0:.1f}s", flush=True)
        new_entries.append(
            {
                "id": eid,
                "text": text,
                "wav": f"wav/{eid}.wav",
                "duration": round(float(dur), 2),
                "motion": _motion_hint(text),
                "category": "miss_filled",
            }
        )

    # re-embed whole library + rewrite index/manifest
    all_entries = manifest["entries"] + new_entries
    try:
        from hevi.live_host.avatar.motionrag import Config, get_embedder

        emb = get_embedder(Config(), allow_audio=False)
        vecs = emb.text([e["text"] for e in all_entries], query=False)
        np.savez_compressed(
            root / "index.npz", ids=np.array([e["id"] for e in all_entries]), text=vecs
        )
        print(f"index.npz rewritten: {vecs.shape}", flush=True)
    except Exception as e:
        print("index rebuild skipped:", e, flush=True)

    manifest["entries"] = all_entries
    manifest["n_entries"] = len(all_entries)
    manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest.json rewritten: {len(all_entries)} entries", flush=True)
    print("FILL DONE", flush=True)


def _duration(wav_path: Path) -> float:
    try:
        import soundfile as sf

        info = sf.info(str(wav_path))
        return round(float(info.frames / info.samplerate), 2)
    except Exception:
        return 0.0


if __name__ == "__main__":
    main()
