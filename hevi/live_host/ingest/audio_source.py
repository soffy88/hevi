"""音频输入源：wav 文件 / 麦克风录制落盘。

麦克风录制需要 sounddevice（可选依赖）；wav 文件直接作为 TurnInput。本机 GPU 不可用
且未装 sounddevice，故 MVP E2E 用 Piper 合成 wav 作为输入，模拟「观众语音提问」。
"""

from __future__ import annotations

import logging
from pathlib import Path

from hevi.live_host.schemas import TurnInput

logger = logging.getLogger(__name__)


def audio_file_source(path: str | Path) -> TurnInput:
    """把 wav 文件作为音频输入。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return TurnInput(audio_path=p, source="wav")


def mic_record_source(output_path: str | Path, duration: float = 5.0) -> TurnInput:
    """录制麦克风 duration 秒到 output_path（需要 sounddevice）。"""
    try:
        import sounddevice as sd
        import soundfile as sf
        import numpy as np
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("麦克风录制需要 sounddevice，请先安装") from exc

    logger.info("录音 %.1fs → %s", duration, output_path)
    data = sd.rec(int(duration * 16000), samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    sf.write(str(output_path), np.asarray(data).reshape(-1), 16000)
    return TurnInput(audio_path=Path(output_path), source="mic")
