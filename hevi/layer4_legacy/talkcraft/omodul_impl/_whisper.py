"""faster-whisper CPU aligner (omodul-private helper: loads a local model)."""

from __future__ import annotations

import os
from typing import Any

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import SentenceTiming
from hevi.layer4_legacy.talkcraft.oskill_impl.align import align_script, chars_from_words

DEFAULT_WHISPER_DIR = os.environ.get(
    "HEVI_TALKCRAFT_WHISPER", "/home/soffy/models/faster-whisper-large-v3-turbo"
)


class WhisperAligner:
    """faster-whisper on CPU (int8).  Loaded once, reused per sentence."""

    name = "faster-whisper-cpu"

    def __init__(self, *, model_dir: str = DEFAULT_WHISPER_DIR, threads: int = 8) -> None:
        from faster_whisper import WhisperModel  # heavy import, local model only

        self.model_dir = model_dir
        self._model: Any = WhisperModel(
            model_dir, device="cpu", compute_type="int8", cpu_threads=threads
        )

    def words(self, *, audio_path: str, language: str, prompt: str) -> list[tuple[str, float, float]]:
        segments, _info = self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=prompt,
        )
        out: list[tuple[str, float, float]] = []
        for seg in segments:
            for w in seg.words or []:
                out.append((w.word, float(w.start), float(w.end)))
        return out

    def align(
        self, *, index: int, text: str, audio_path: str, start_s: float, end_s: float, language: str
    ) -> SentenceTiming:
        words = self.words(audio_path=audio_path, language=language, prompt=text)
        chars, ratio = align_script(
            script=text, asr_chars=chars_from_words(words=words), start_s=start_s, end_s=end_s
        )
        return SentenceTiming(
            index=index,
            text=text,
            start_s=start_s,
            end_s=end_s,
            chars=tuple(chars),
            match_ratio=round(ratio, 4),
            aligner=self.name,
        )
