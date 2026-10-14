"""CosyVoice3 English (cross-lingual) quality A/B — pick the pipeline for Part B.

The Part B pilot needs English spoken in Xiaoya's female voice.  Compare the
candidate pipelines on a few real Unit 1 sentences:

  A. zero_shot(English text, zh_prompt_text, zero_shot_prompt.wav)
     — what build_unit.py used first; the prompt is the Chinese reading prompt,
       so the English may be accented/garbled.
  B. cross_lingual('<|en|>' + text, cross_lingual_prompt.wav)
     — CosyVoice3's dedicated English path; good English but the prompt audio is
       a DIFFERENT speaker.
  C. cross_lingual(..., cross_lingual_prompt.wav) then
     vc(<that wav>, zero_shot_prompt.wav)
     — English prosody, then voice-converted into Xiaoya's voice (the pattern
       CosyVoice's own example.py shows).  This is the one we want if it holds up.

Writes one wav per (method, sentence) plus a JSON summary so the choice can be
audited by ear.  Run AFTER the Part A generation finishes (same model, so it
would otherwise compete for RAM/CPU).

    TMPDIR=/data/soffy/voicecache/tmp \\
    /data/soffy/cosyvoice/venv/bin/python hevi/live_host/eng_lib/en_quality_ab.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

COSY_DIR = "/data/soffy/cosyvoice/CosyVoice"
MODEL_DIR = "/data/soffy/cosyvoice/models/Fun-CosyVoice3-0.5B"
ZH_PROMPT_TEXT = "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。"
ZH_PROMPT_WAV = "./asset/zero_shot_prompt.wav"
XL_PROMPT_WAV = "./asset/cross_lingual_prompt.wav"

OUT = Path("/data/soffy/voicecache/tmp/en_ab")

SENTS = [
    ("k04", "Hello!"),
    ("k06", "Nice to meet you."),
    ("d01", "Good morning. I'm Teng Fei. What's your name?"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    os.chdir(COSY_DIR)
    sys.path += [".", "third_party/Matcha-TTS"]
    import torch
    import torchaudio

    torch.set_num_threads(int(os.environ.get("HEVI_LIVE_THREADS", "8")))
    from cosyvoice.cli.cosyvoice import AutoModel

    m = AutoModel(model_dir=MODEL_DIR)
    summary = []

    for sid, text in SENTS:
        row = {"id": sid, "text": text, "methods": {}}

        # A: zero-shot with the Chinese prompt
        t0 = time.time()
        a = torch.cat(
            [
                j["tts_speech"]
                for j in m.inference_zero_shot(text, ZH_PROMPT_TEXT, ZH_PROMPT_WAV, stream=False)
            ],
            1,
        )
        torchaudio.save(str(OUT / f"A_{sid}.wav"), a, m.sample_rate)
        row["methods"]["A_zero_shot_zhprompt"] = {
            "dur": round(a.shape[1] / m.sample_rate, 2),
            "gen_s": round(time.time() - t0, 1),
        }

        # B: cross-lingual (its own prompt → English quality, other speaker)
        t0 = time.time()
        b = torch.cat(
            [
                j["tts_speech"]
                for j in m.inference_cross_lingual(f"<|en|>{text}", XL_PROMPT_WAV, stream=False)
            ],
            1,
        )
        torchaudio.save(str(OUT / f"B_{sid}.wav"), b, m.sample_rate)
        row["methods"]["B_cross_lingual"] = {
            "dur": round(b.shape[1] / m.sample_rate, 2),
            "gen_s": round(time.time() - t0, 1),
        }

        # C: cross-lingual → voice conversion into Xiaoya's voice
        t0 = time.time()
        c = torch.cat([j["tts_speech"] for j in m.inference_vc(b, ZH_PROMPT_WAV, stream=False)], 1)
        torchaudio.save(str(OUT / f"C_{sid}.wav"), c, m.sample_rate)
        row["methods"]["C_xl_then_vc"] = {
            "dur": round(c.shape[1] / m.sample_rate, 2),
            "gen_s": round(time.time() - t0, 1),
        }

        summary.append(row)
        print(
            f"{sid} A={row['methods']['A_zero_shot_zhprompt']['dur']}s "
            f"B={row['methods']['B_cross_lingual']['dur']}s "
            f"C={row['methods']['C_xl_then_vc']['dur']}s",
            flush=True,
        )

    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("EN AB DONE", flush=True)


if __name__ == "__main__":
    main()
