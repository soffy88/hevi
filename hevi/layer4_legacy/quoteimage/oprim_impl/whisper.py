from __future__ import annotations

import os
from typing import Any

DEFAULT_WHISPER_DIR = os.environ.get(
    "HEVI_TALKCRAFT_WHISPER", "/home/soffy/models/faster-whisper-large-v3-turbo"
)

class WhisperAligner:
    name = "faster-whisper-cpu"

    def __init__(self, *, model_dir: str = DEFAULT_WHISPER_DIR, threads: int = 8) -> None:
        from faster_whisper import WhisperModel
        self.model_dir = model_dir
        self._model = WhisperModel(
            model_dir, device="cpu", compute_type="int8", cpu_threads=threads
        )

    def transcribe_segments(self, audio_path: str, language: str | None = None) -> list[dict[str, Any]]:
        segments, _info = self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=1,
            vad_filter=False,
        )
        results = []
        sentence_endings = (".", "?", "!", "。", "！", "？", ";", "；")
        for seg in segments:
            words = getattr(seg, "words", None)
            if words:
                cur_words = []
                for w in words:
                    cur_words.append(w)
                    if any(w.word.endswith(punct) for punct in sentence_endings):
                        t_start = cur_words[0].start
                        t_sample = round(t_start + min(1.0, (cur_words[-1].end - t_start) * 0.4), 2)
                        txt = "".join(x.word for x in cur_words).strip()
                        if txt:
                            results.append({"t": t_sample, "text": txt,
                                            "start": round(float(t_start), 2),
                                            "end": round(float(cur_words[-1].end), 2)})
                        cur_words = []
                if cur_words:
                    t_start = cur_words[0].start
                    t_sample = round(t_start + min(1.0, (cur_words[-1].end - t_start) * 0.4), 2)
                    txt = "".join(x.word for x in cur_words).strip()
                    if txt:
                        results.append({"t": t_sample, "text": txt,
                                        "start": round(float(t_start), 2),
                                        "end": round(float(cur_words[-1].end), 2)})
            else:
                txt = seg.text.strip()
                if txt:
                    t_sample = round(float(seg.start) + 0.5, 2)
                    results.append({"t": t_sample, "text": txt,
                                    "start": round(float(seg.start), 2), "end": round(float(seg.end), 2)})
        return results
