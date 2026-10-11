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
            word_timestamps=False,
            beam_size=1,
            vad_filter=False,
        )
        return [{"t": float(seg.start), "text": seg.text.strip()} for seg in segments]
