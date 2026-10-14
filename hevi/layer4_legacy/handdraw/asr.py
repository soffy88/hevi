"""Local CPU ASR (faster-whisper) used to force-align narration to the audio.

The handdraw line must not fabricate caption timings by proportional character
counts: cue boundaries are derived from word-level timestamps produced by a
local CPU model.  No network, no paid API.

If the model is unavailable the caller records ``method="proportional"`` and the
verification report says so explicitly; it never claims ASR alignment happened.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Vendored local model snapshot (Systran/faster-whisper-small), CPU int8.
_WHISPER_DIR = Path(
    "/data/soffy/appdata/huggingface_hub/models--Systran--faster-whisper-small"
    "/snapshots/536b0662742c02347bc0e980a01041f333bce120"
)
_ALT_DIRS = (
    Path("/data/soffy/models/hf/hub/models--Systran--faster-whisper-small/snapshots"),
    Path("/data/soffy/appdata/huggingface_hub/models--Systran--faster-whisper-small/snapshots"),
)


def _resolve_model_dir() -> Path | None:
    if (_WHISPER_DIR / "model.bin").is_file():
        return _WHISPER_DIR
    for base in _ALT_DIRS:
        if base.is_dir():
            for snapshot in sorted(base.iterdir(), reverse=True):
                if (snapshot / "model.bin").is_file():
                    return snapshot
    return None


@lru_cache(maxsize=1)
def _model() -> Any:
    from faster_whisper import WhisperModel  # imported lazily; CPU only

    directory = _resolve_model_dir()
    if directory is None:
        raise FileNotFoundError("faster-whisper model snapshot not found locally")
    return WhisperModel(str(directory), device="cpu", compute_type="int8")


def asr_available() -> bool:
    try:
        _model()
        return True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.info("ASR unavailable: %s", exc)
        return False


def transcribe_words(wav_path: Path | str) -> list[dict[str, Any]]:
    """Return word-level timestamps for a mono 48k wav.

    Raises if the model cannot be loaded; callers must handle the absence and
    record the fallback honestly instead of pretending alignment happened.
    """
    model = _model()
    segments, _info = model.transcribe(
        str(wav_path), language="zh", word_timestamps=True, vad_filter=False
    )
    words: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.words or []:
            text = str(word.word).strip()
            if text:
                words.append(
                    {"text": text, "start": float(word.start), "end": float(word.end)}
                )
    return words
