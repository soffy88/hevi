"""ASR-score the CosyVoice3 English A/B clips to pick the Part B pipeline.

Reads the wavs written by en_quality_ab.py, transcribes each with faster-whisper
(English) and reports word error rate vs the reference sentence.  WER is a
proxy for intelligibility: a low WER means a listener (or a student) hears the
right English words.  The voice timbre is judged separately (the A/C clips use
Xiaoya's prompt, so A/C are "Xiaoya's voice"; B is a different speaker).

    PYTHONPATH=/data/soffy/projects/hevi-live \\
    /data/soffy/projects/hevi/.venv/bin/python \\
        hevi/live_host/eng_lib/en_quality_score.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODEL = "/home/soffy/models/faster-whisper-large-v3-turbo"


def _norm(s: str) -> list[str]:
    s = s.lower()
    s = re.sub(r"[^a-z0-9' ]+", " ", s)
    return s.split()


def wer(ref: str, hyp: str) -> float:
    r, h = _norm(ref), _norm(hyp)
    if not r:
        return 0.0 if not h else 1.0
    # Levenshtein on word tokens
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ab", default="/data/soffy/voicecache/tmp/en_ab")
    ap.add_argument("--out", default="/data/soffy/voicecache/tmp/en_ab/quality.json")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()
    ab = Path(args.ab)

    summary = json.loads((ab / "summary.json").read_text(encoding="utf-8"))

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    per_method: dict[str, list[float]] = {}
    rows = []
    for row in summary:
        ref = row["text"]
        rec = {"id": row["id"], "text": ref, "methods": {}}
        for tag, info in row["methods"].items():
            if "wav" not in info:
                rec["methods"][tag] = {"error": info.get("error", "no wav")}
                continue
            wav = ab / info["wav"]
            segs, _ = model.transcribe(str(wav), language="en", beam_size=1)
            hyp = "".join(s.text for s in segs).strip()
            w = wer(ref, hyp)
            per_method.setdefault(tag, []).append(w)
            rec["methods"][tag] = {"wer": round(w, 3), "asr": hyp}
        rows.append(rec)

    agg = {
        tag: {"mean_wer": round(sum(v) / len(v), 3), "n": len(v)}
        for tag, v in sorted(per_method.items())
    }
    best = min(agg, key=lambda t: agg[t]["mean_wer"]) if agg else None
    out = {"per_sentence": rows, "aggregate": agg, "best_by_wer": best}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for tag, a in agg.items():
        print(f"{tag}: mean_wer={a['mean_wer']} (n={a['n']})", flush=True)
    print(f"BEST_BY_WER={best}", flush=True)
    print("EN SCORE DONE", flush=True)


if __name__ == "__main__":
    main()
