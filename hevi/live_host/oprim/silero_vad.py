"""Silero VAD（onnx）语音活动检测原子。

直接从 faster-whisper 内置资产加载 silero_vad_v6.onnx，CPU 推理，带 GRU 状态。
输入窗口 576 采样（16kHz），带 h/c 状态跨窗口传递，输出逐帧 speech 概率。
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from hevi.live_host.schemas import Engine

logger = logging.getLogger(__name__)

_WINDOW = 576  # 16kHz 下 36ms
_STATE = np.zeros((1, 1, 128), dtype=np.float32)


def _default_model() -> Path:
    import faster_whisper

    base = Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"
    if not base.exists():  # pragma: no cover - 资产随包安装
        raise FileNotFoundError(f"Silero VAD 资产缺失: {base}")
    return base


class SileroVAD(Engine):
    """逐窗口语音概率；speech 判定阈值 0.5。"""

    name = "silero_vad"

    def __init__(self, model_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path) if model_path else _default_model()
        self._sess = ort.InferenceSession(str(self.model_path), providers=["CPUExecutionProvider"])

    def available(self) -> bool:
        return self.model_path.exists()

    def reset(self) -> None:
        self._h = _STATE.copy()
        self._c = _STATE.copy()

    def _ensure(self) -> None:
        if not hasattr(self, "_h"):
            self.reset()

    def probabilities(self, samples: np.ndarray) -> list[float]:
        """对 16kHz float32 单声道音频返回逐窗口 speech 概率列表。"""
        self._ensure()
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        samples = np.asarray(samples, dtype=np.float32)
        out: list[float] = []
        for i in range(0, max(1, len(samples) - _WINDOW), _WINDOW):
            x = samples[i : i + _WINDOW].reshape(1, -1)
            res = self._sess.run(None, {"input": x, "h": self._h, "c": self._c})
            prob, self._h, self._c = res[0].item(), res[1], res[2]
            out.append(float(prob))
        return out

    def has_speech(
        self, samples: np.ndarray, threshold: float = 0.5, min_ratio: float = 0.05
    ) -> bool:
        """片段中是否含有效语音（语音帧占比超过 min_ratio）。"""
        probs = self.probabilities(samples)
        if not probs:
            return False
        return sum(1 for p in probs if p > threshold) / len(probs) >= min_ratio
