"""faster-whisper STT 原子（CPU 默认，int8）。"""

from __future__ import annotations

import logging
from pathlib import Path

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)


class WhisperSTT(Engine):
    """转写 16kHz wav 文件为中文文本。"""

    name = "whisper"

    def __init__(
        self,
        model_path: str | Path = "/home/soffy/models/faster-whisper-large-v3-turbo",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_path = str(model_path)
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def available(self) -> bool:
        return Path(self.model_path).exists()

    def _ensure(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_path, device=self.device, compute_type=self.compute_type
            )

    def transcribe(self, audio_path: str | Path, language: str = "zh") -> str:
        self._ensure()
        segs, _ = self._model.transcribe(str(audio_path), language=language, beam_size=1)
        return "".join(s.text for s in segs).strip()
