"""Build ONE English-textbook practice unit for the Xiaoya English 陪练 library.

Prototype (see /data/soffy/voicecache/brief.md Part B): pre-generate, per
textbook sentence, an English audio clip in Xiaoya's voice (CosyVoice3
cross-lingual zero-shot, same female prompt as the reading feature), a Chinese
gloss, and EG2 text vectors, so the practice loop can retrieve + replay cached
audio instead of real-time TTS.

Source: PEP 人教版英语 七年级上 Unit 1 "Hello!" — sentences verified against both
mneme's local OCR export (reports/vocab_memory_p0/pep_ocr_sentences.json) and
the mneme Postgres `textbook_sentences` table (read-only, local docker instance;
textbook id ``pep-en-g7a``).  Units are page-indexed there, and Unit 1 occupies
pages 11-15; pages 7-9 belong to the opening starter page / other units and
page 16+ is OCR noise, so we curate the Unit 1 cluster here (with Chinese
glosses) rather than trusting noisy OCR verbatim.

Note the license: these rows are ``license_status='unlicensed'`` (student-facing
copyrighted textbook content), which is why this is a single-unit local pilot
only — see docs/xiaoya_practice.md in mneme.

Output (for book=pep-g7a, unit=u1):

    /data/soffy/englib/pep-g7a/u1/
        manifest.json     {unit meta, items[]}
        wav/<id>.wav      24 kHz mono English audio (Xiaoya voice)
        index.npz         EG2 text vectors (ids, text) for retrieval

Run with the CosyVoice venv:

    TMPDIR=/data/soffy/voicecache/tmp \\
    /data/soffy/cosyvoice/venv/bin/python \\
        hevi/live_host/eng_lib/build_unit.py [--book pep-g7a] [--unit u1] [--root /data/soffy/englib]

Idempotent: existing wavs are skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

# ---- CosyVoice3 (same female voice as reading feature) ----
COSY_DIR = "/data/soffy/cosyvoice/CosyVoice"
MODEL_DIR = "/data/soffy/cosyvoice/models/Fun-CosyVoice3-0.5B"
PROMPT_WAV = "./asset/zero_shot_prompt.wav"
PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"

DEFAULT_ROOT = Path(os.environ.get("HEVI_ENGLIB_ROOT", "/data/soffy/englib"))


# Curated Unit 1 content (greetings + introductions + name-spelling cluster).
# kind: key_sentence | dialogue | vocabulary
UNIT = {
    "book": "pep-g7a",
    "unit": "u1",
    "title": "七年级上 Unit 1 Hello! (greetings & introductions)",
    "items": [
        # ---- greetings / key sentences ----
        {
            "id": "k01",
            "kind": "key_sentence",
            "text": "Good morning.",
            "gloss": "早上好。",
            "motion": "g_wave",
        },
        {
            "id": "k02",
            "kind": "key_sentence",
            "text": "Good afternoon.",
            "gloss": "下午好。",
            "motion": "g_wave",
        },
        {
            "id": "k03",
            "kind": "key_sentence",
            "text": "Good evening.",
            "gloss": "晚上好。",
            "motion": "g_wave",
        },
        {
            "id": "k04",
            "kind": "key_sentence",
            "text": "Hello!",
            "gloss": "你好！",
            "motion": "g_wave",
        },
        {
            "id": "k05",
            "kind": "key_sentence",
            "text": "Hi, Helen.",
            "gloss": "你好，海伦。",
            "motion": "g_wave",
        },
        {
            "id": "k06",
            "kind": "key_sentence",
            "text": "Nice to meet you.",
            "gloss": "很高兴认识你。",
            "motion": "g_nod",
        },
        {
            "id": "k07",
            "kind": "key_sentence",
            "text": "Nice to meet you too.",
            "gloss": "我也很高兴认识你。",
            "motion": "g_nod",
        },
        {
            "id": "k08",
            "kind": "key_sentence",
            "text": "I'm fine, thank you. And you?",
            "gloss": "我很好，谢谢。你呢？",
            "motion": "talk_a",
        },
        {
            "id": "k09",
            "kind": "key_sentence",
            "text": "How are you?",
            "gloss": "你好吗？",
            "motion": "talk_a",
        },
        {
            "id": "k10",
            "kind": "key_sentence",
            "text": "I'm fine too.",
            "gloss": "我也很好。",
            "motion": "talk_a",
        },
        # ---- introductions / dialogues ----
        {
            "id": "d01",
            "kind": "dialogue",
            "text": "Good morning. I'm Teng Fei. What's your name?",
            "gloss": "早上好。我是腾飞。你叫什么名字？",
            "motion": "talk_a",
        },
        {
            "id": "d02",
            "kind": "dialogue",
            "text": "My name is Emma Miller.",
            "gloss": "我叫艾玛·米勒。",
            "motion": "talk_a",
        },
        {
            "id": "d03",
            "kind": "dialogue",
            "text": "You can call me Emma.",
            "gloss": "你可以叫我艾玛。",
            "motion": "talk_a",
        },
        {
            "id": "d04",
            "kind": "dialogue",
            "text": "What's your name?",
            "gloss": "你叫什么名字？",
            "motion": "talk_a",
        },
        {
            "id": "d05",
            "kind": "dialogue",
            "text": "How do you spell your name?",
            "gloss": "你的名字怎么拼？",
            "motion": "talk_a",
        },
        {
            "id": "d06",
            "kind": "dialogue",
            "text": "Hello, Wang Yaming!",
            "gloss": "你好，王亚明！",
            "motion": "g_wave",
        },
        {
            "id": "d07",
            "kind": "dialogue",
            "text": "Good morning, Ms Gao.",
            "gloss": "早上好，高老师。",
            "motion": "g_wave",
        },
        {
            "id": "d08",
            "kind": "dialogue",
            "text": "Thank you, Peter.",
            "gloss": "谢谢你，彼得。",
            "motion": "g_heart",
        },
        # ---- remaining Unit 1 (p11-15) sentences from the mneme DB ----
        {
            "id": "d09",
            "kind": "dialogue",
            "text": "Good morning, Ella and Emma!",
            "gloss": "早上好，埃拉和埃玛！",
            "motion": "g_wave",
        },
        {
            "id": "d10",
            "kind": "dialogue",
            "text": "Hi, Helen. I'm fine, thank you. And you?",
            "gloss": "你好，海伦。我很好，谢谢。你呢？",
            "motion": "talk_a",
        },
        {
            "id": "d11",
            "kind": "dialogue",
            "text": "Nice to meet you too, Teng Fei.",
            "gloss": "我也很高兴认识你，腾飞。",
            "motion": "g_nod",
        },
        {
            "id": "d12",
            "kind": "dialogue",
            "text": "Hi, Helen. I'm fine, thank you.",
            "gloss": "你好，海伦。我很好，谢谢。",
            "motion": "talk_a",
        },
        {
            "id": "k11",
            "kind": "key_sentence",
            "text": "I'm fine, thank you.",
            "gloss": "我很好，谢谢。",
            "motion": "g_nod",
        },
        {
            "id": "k12",
            "kind": "key_sentence",
            "text": "What can you learn from different subjects?",
            "gloss": "你能从不同学科中学到什么？",
            "motion": "talk_a",
        },
        {
            "id": "k13",
            "kind": "key_sentence",
            "text": "Good morning. My name is Emma Miller.",
            "gloss": "早上好。我叫艾玛·米勒。",
            "motion": "talk_a",
        },
        # ---- vocabulary ----
        {
            "id": "v01",
            "kind": "vocabulary",
            "text": "morning",
            "gloss": "早晨；上午",
            "motion": "talk_a",
        },
        {
            "id": "v02",
            "kind": "vocabulary",
            "text": "afternoon",
            "gloss": "下午",
            "motion": "talk_a",
        },
        {"id": "v03", "kind": "vocabulary", "text": "evening", "gloss": "晚上", "motion": "talk_a"},
        {"id": "v04", "kind": "vocabulary", "text": "name", "gloss": "名字", "motion": "talk_a"},
        {"id": "v05", "kind": "vocabulary", "text": "spell", "gloss": "拼写", "motion": "talk_a"},
        {
            "id": "v06",
            "kind": "vocabulary",
            "text": "meet",
            "gloss": "遇见；结识",
            "motion": "talk_a",
        },
        {
            "id": "v07",
            "kind": "vocabulary",
            "text": "fine",
            "gloss": "身体好的；健康的",
            "motion": "talk_a",
        },
        {
            "id": "v08",
            "kind": "vocabulary",
            "text": "call",
            "gloss": "称呼；呼叫",
            "motion": "talk_a",
        },
        {
            "id": "v09",
            "kind": "vocabulary",
            "text": "classmate",
            "gloss": "同班同学",
            "motion": "talk_a",
        },
        {
            "id": "v10",
            "kind": "vocabulary",
            "text": "greet",
            "gloss": "问候；打招呼",
            "motion": "g_wave",
        },
        {
            "id": "v11",
            "kind": "vocabulary",
            "text": "conversation",
            "gloss": "对话；交谈",
            "motion": "talk_a",
        },
        {
            "id": "v12",
            "kind": "vocabulary",
            "text": "start",
            "gloss": "开始",
            "motion": "talk_a",
        },
    ],
}


def load_model():
    os.chdir(COSY_DIR)
    sys.path += [".", "third_party/Matcha-TTS"]
    import torch
    import torchaudio

    torch.set_num_threads(int(os.environ.get("HEVI_LIVE_THREADS", "8")))
    from cosyvoice.cli.cosyvoice import AutoModel

    m = AutoModel(model_dir=MODEL_DIR)
    return m, torch, torchaudio


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=UNIT["book"])
    ap.add_argument("--unit", default=UNIT["unit"])
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--skip-gen", action="store_true")
    args = ap.parse_args()

    root = Path(args.root) / args.book / args.unit
    wav_dir = root / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    items = UNIT["items"]
    print(f"unit {args.book}/{args.unit}: {len(items)} items", flush=True)

    model = None
    total_audio = 0.0
    for it in items:
        out = wav_dir / f"{it['id']}.wav"
        it["wav"] = f"wav/{it['id']}.wav"
        if out.exists() and out.stat().st_size > 0:
            it["duration"] = _duration(out)
            continue
        if args.skip_gen:
            continue
        if model is None:
            model, torch, torchaudio = load_model()
        t0 = time.time()
        # cross-lingual zero-shot: English text, Chinese-voice prompt
        w = torch.cat(
            [
                j["tts_speech"]
                for j in model.inference_zero_shot(
                    it["text"], PROMPT_TEXT, PROMPT_WAV, stream=False
                )
            ],
            1,
        )
        torchaudio.save(str(out), w, model.sample_rate)
        dur = w.shape[1] / model.sample_rate
        it["duration"] = round(float(dur), 2)
        total_audio += dur
        print(
            f"{it['id']} '{it['text'][:24]}' dur={dur:.2f}s gen={time.time() - t0:.1f}s", flush=True
        )

    _build_index(items, root)
    _write_manifest(args.book, args.unit, items, root)
    print(f"TOTAL audio_seconds={total_audio:.1f} ENG UNIT DONE", flush=True)


def _duration(wav_path: Path) -> float:
    try:
        import soundfile as sf

        info = sf.info(str(wav_path))
        return round(float(info.frames / info.samplerate), 2)
    except Exception:
        return 0.0


def _build_index(items: list[dict], root: Path) -> None:
    try:
        from hevi.live_host.avatar.motionrag import Config, get_embedder
    except Exception as e:
        print("skip index (no embedder):", e, flush=True)
        return
    try:
        emb = get_embedder(Config(), allow_audio=False)
    except Exception as e:
        print("skip index (embedder unavailable):", e, flush=True)
        return
    texts = [i["text"] for i in items]
    vecs = emb.text(texts, query=False)
    np.savez_compressed(root / "index.npz", ids=np.array([i["id"] for i in items]), text=vecs)
    print(f"index.npz written: {vecs.shape}", flush=True)


def _write_manifest(book: str, unit: str, items: list[dict], root: Path) -> None:
    entries = [
        i for i in items if (root / i["wav"]).exists() and (root / i["wav"]).stat().st_size > 0
    ]
    manifest = {
        "book": book,
        "unit": unit,
        "title": UNIT["title"],
        "voice": "Xiaoya (小雅) — CosyVoice3 cross-lingual zero-shot",
        "sample_rate": 24000,
        "channels": 1,
        "dim": 768,
        "n_items": len(entries),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": [
            {
                "id": e["id"],
                "kind": e["kind"],
                "text": e["text"],
                "gloss": e["gloss"],
                "wav": e["wav"],
                "duration": e.get("duration", 0.0),
                "motion": e["motion"],
            }
            for e in entries
        ],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifest.json written: {len(entries)} items", flush=True)


if __name__ == "__main__":
    main()
