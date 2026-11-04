"""faster-whisper CPU 运行时（int8，小模型）。返回词级时间戳，不做断句。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_MODEL = os.environ.get("HEVI_WHISPER_MODEL", "/data/soffy/models/faster-whisper-base")


@lru_cache(maxsize=2)
def _model(model: str, threads: int):
    from faster_whisper import WhisperModel  # 延迟导入，避免拖慢无 ASR 场景

    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads)


def transcribe_words(
    path: str | Path,
    model: str | None = None,
    language: str | None = None,
    vad: bool = True,
    beam_size: int = 1,
) -> dict:
    """→ {"language", "duration", "words": [{"start","end","word"}], "segments": [{"start","end","text"}]}"""
    m = _model(model or DEFAULT_MODEL, int(os.environ.get("HEVI_WHISPER_THREADS", "4")))
    segs, info = m.transcribe(
        str(path),
        language=language,
        vad_filter=vad,
        word_timestamps=True,
        beam_size=beam_size,
        condition_on_previous_text=False,
    )
    words, segments = [], []
    for s in segs:
        segments.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": float(w.start), "end": float(w.end), "word": w.word})
    return {
        "language": info.language,
        "duration": info.duration,
        "words": words,
        "segments": segments,
    }
