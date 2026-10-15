"""CosyVoice3 English quality A/B — pick the pipeline for Part B.

The Part B pilot needs English spoken in Xiaoya's female voice.  Compare the
candidate pipelines on real Unit 1 sentences:

  A. zero_shot(English text, zh_prompt_text, zero_shot_prompt.wav)
     — the zh reading prompt == Xiaoya's voice; the English may be accented.
  B. cross_lingual(EN_PROMPT + text, EN_PROMPT_WAV)
     — CosyVoice3's dedicated English path; good English, different speaker.
  C. B then vc(<that wav>, zero_shot_prompt.wav)
     — English prosody, voice-converted into Xiaoya's voice.

CosyVoice3LM asserts `<|endofprompt|>` is present in the (text+prompt) token
stream, so the cross-lingual TEXT must carry the `You are a helpful assistant.
<|endofprompt|>` prefix (see CosyVoice/example.py); `<|en|>` alone trips the
assert.  B also gets an English prompt wav (its own speaker) so C has a clean
English source to convert from.

Each method is wrapped so one failure does not abort the run.  Writes one wav
per (method, sentence) plus a JSON summary; en_quality_score.py ASR-scores them.

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
# CosyVoice3LM requires <|endofprompt|> in the text; the English cross-lingual
# path takes the same assistant preamble.  Its own prompt wav is a clean English
# speaker (B), which C then voice-converts into Xiaoya's timbre.
EN_PROMPT = "You are a helpful assistant.<|endofprompt|>"
XL_PROMPT_WAV = "./asset/cross_lingual_prompt.wav"

OUT = Path(os.environ.get("HEVI_EN_AB_OUT", "/data/soffy/voicecache/tmp/en_ab"))

# a spread of Unit 1 content: 1-word vocab, short greetings, a full dialogue line
SENTS = [
    ("k04", "Hello!"),
    ("v01", "morning"),
    ("k06", "Nice to meet you."),
    ("k09", "How are you?"),
    ("k05", "Hi, Helen."),
    ("k08", "I'm fine, thank you. And you?"),
    ("d01", "Good morning. I'm Teng Fei. What's your name?"),
    ("d05", "How do you spell your name?"),
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

    def _save(tag: str, sid: str, t0: float, w, row: dict) -> None:
        torchaudio.save(str(OUT / f"{tag}_{sid}.wav"), w, m.sample_rate)
        row["methods"][tag] = {
            "dur": round(w.shape[1] / m.sample_rate, 2),
            "gen_s": round(time.time() - t0, 1),
            "wav": f"{tag}_{sid}.wav",
        }

    summary = []
    for sid, text in SENTS:
        row: dict = {"id": sid, "text": text, "methods": {}}

        # A: zero-shot with the Chinese (Xiaoya) prompt
        try:
            t0 = time.time()
            a = torch.cat(
                [
                    j["tts_speech"]
                    for j in m.inference_zero_shot(
                        text, ZH_PROMPT_TEXT, ZH_PROMPT_WAV, stream=False
                    )
                ],
                1,
            )
            _save("A", sid, t0, a, row)
        except Exception as e:  # noqa: BLE001
            row["methods"]["A_zero_shot_zhprompt"] = {"error": f"{type(e).__name__}: {e}"[:160]}

        # B: cross-lingual (English path, other speaker)
        b = None
        try:
            t0 = time.time()
            b = torch.cat(
                [
                    j["tts_speech"]
                    for j in m.inference_cross_lingual(
                        f"{EN_PROMPT}{text}", XL_PROMPT_WAV, stream=False
                    )
                ],
                1,
            )
            _save("B", sid, t0, b, row)
        except Exception as e:  # noqa: BLE001
            row["methods"]["B_cross_lingual"] = {"error": f"{type(e).__name__}: {e}"[:160]}

        # C: cross-lingual -> voice conversion into Xiaoya's voice.
        # inference_vc takes a *path*, so write B's English source to disk first
        # (that wav is also what the final unit build would convert in place).
        if b is not None:
            try:
                t0 = time.time()
                src = OUT / f"B_{sid}.wav"
                c = torch.cat(
                    [
                        j["tts_speech"]
                        for j in m.inference_vc(str(src), ZH_PROMPT_WAV, stream=False)
                    ],
                    1,
                )
                _save("C", sid, t0, c, row)
            except Exception as e:  # noqa: BLE001
                row["methods"]["C_xl_then_vc"] = {"error": f"{type(e).__name__}: {e}"[:160]}

        summary.append(row)
        got = {k: (v.get("dur") if "dur" in v else "ERR") for k, v in row["methods"].items()}
        print(f"{sid} {text[:30]!r} -> {got}", flush=True)

    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("EN AB DONE", flush=True)


if __name__ == "__main__":
    main()
