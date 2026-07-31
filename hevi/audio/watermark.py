"""音频水印 — AudioSeal 启发的频域水印嵌入/检测。

用于标记 AI 生成音频,支持版权追踪。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["AudioWatermarker", "embed_watermark", "detect_watermark"]


class AudioWatermarker:
    """音频水印器。

    使用频域方法 (DCT/FFT) 嵌入不可听水印。
    对标 AudioSeal (Meta) 的盲水印方案。
    """

    def __init__(self, sample_rate: int = 48000, bit_depth: int = 16):
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth

    async def embed(self, audio_path: Path, message: str, output_path: Path) -> Path:
        """嵌入水印到音频文件。

        方法:
          1. 读取 PCM 音频
          2. FFT 变换到频域
          3. 在中频带嵌入消息比特
          4. IFFT 逆变换回时域
          5. 输出
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Embedding watermark '%s' into %s → %s", message, audio_path.name, output_path)

        # Stub: In production, use numpy/scipy for actual DSP
        # import numpy as np
        # from scipy.io import wavfile
        # sr, data = wavfile.read(audio_path)
        # spectrum = np.fft.rfft(data)
        # ... embed message bits in mid-frequency bins ...
        # watermarked = np.fft.irfft(spectrum)
        # wavfile.write(output_path, sr, watermarked.astype(np.int16))

        # For now, copy file as placeholder
        import shutil
        shutil.copy2(audio_path, output_path)

        return output_path

    async def detect(self, audio_path: Path) -> Optional[str]:
        """检测并提取音频中的水印消息。"""
        if not audio_path.exists():
            return None

        logger.info("Detecting watermark in %s", audio_path.name)

        # Stub: FFT + extract bits from mid-frequency bins
        return None


async def embed_watermark(audio_path: Path, message: str, output_path: Path) -> Path:
    """便捷函数: 嵌入水印。"""
    wm = AudioWatermarker()
    return await wm.embed(audio_path, message, output_path)


async def detect_watermark(audio_path: Path) -> Optional[str]:
    """便捷函数: 检测水印。"""
    wm = AudioWatermarker()
    return await wm.detect(audio_path)
