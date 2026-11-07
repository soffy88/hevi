"""ASR 双语字幕模块：faster-whisper(CPU int8) → 断句 → Ollama 本地翻译 → SRT/ASS。

CLI: python -m hevi.avcraft.omodul.bilingual_subs IN OUT_DIR [--tgt zh|en] [--lang auto] [--glossary g.json] [--no-translate]
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path

from hevi.avcraft.obase.asr_runtime import transcribe_words
from hevi.avcraft.obase.llm_local import ollama_generate
from hevi.avcraft.oskill.subtitle import segment_sentences, to_ass, to_srt, translate_cues


def bilingual_subtitles(
    src: str | Path,
    out_dir: str | Path,
    *,
    tgt: str | None = None,
    language: str | None = None,
    glossary: dict | None = None,
    translate: bool = True,
    model: str | None = None,
    llm: Callable[[str], str] | None = None,
    llm_model: str | None = None,
) -> dict:
    src = Path(src)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    asr = transcribe_words(src, model=model, language=language)
    t_asr = time.time() - t0
    cues = segment_sentences(asr["words"])
    lang = asr["language"]
    tgt = tgt or ("en" if lang == "zh" else "zh")
    t_tr = 0.0
    if translate and cues and tgt != lang:
        t1 = time.time()
        fn = llm or (lambda p: ollama_generate(p, model=llm_model, fmt="json"))
        cues = translate_cues(cues, fn, src=lang, tgt=tgt, glossary=glossary)
        t_tr = time.time() - t1
    stem = src.stem
    files = {
        "json": out / f"{stem}.cues.json",
        "srt_src": out / f"{stem}.{lang}.srt",
    }
    files["json"].write_text(
        json.dumps({"language": lang, "target": tgt, "cues": cues}, ensure_ascii=False, indent=1)
    )
    files["srt_src"].write_text(to_srt(cues, "src"))
    if any(c.get("tr") for c in cues):
        files["srt_tr"] = out / f"{stem}.{tgt}.srt"
        files["srt_tr"].write_text(to_srt(cues, "tr"))
        files["srt_bi"] = out / f"{stem}.{lang}-{tgt}.srt"
        files["srt_bi"].write_text(to_srt(cues, "bilingual"))
    files["ass"] = out / f"{stem}.{lang}-{tgt}.ass"
    files["ass"].write_text(to_ass(cues))
    return {
        "language": lang,
        "target": tgt,
        "cues": len(cues),
        "words": len(asr["words"]),
        "asr_s": round(t_asr, 1),
        "translate_s": round(t_tr, 1),
        "files": {k: str(v) for k, v in files.items()},
    }


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--tgt")
    ap.add_argument("--lang")
    ap.add_argument("--glossary")
    ap.add_argument("--model")
    ap.add_argument("--llm-model")
    ap.add_argument("--no-translate", action="store_true")
    a = ap.parse_args()
    g = json.loads(Path(a.glossary).read_text()) if a.glossary else None
    r = bilingual_subtitles(
        a.src,
        a.out,
        tgt=a.tgt,
        language=a.lang,
        glossary=g,
        translate=not a.no_translate,
        model=a.model,
        llm_model=a.llm_model,
    )
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()
