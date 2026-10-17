"""voice_embed — 音色向量原语(hevi 参考实现),镜像 `hevi.subjects.subject_embed` 的
CLIP 视觉向量套路,换成 resemblyzer 的 d-vector(说话人识别用的音色嵌入,不是内容/ASR)。

后端选型:resemblyzer 的预训练权重打包在 pip 包里,不需要联网下载(同
`subject_embed.py` 顶部注释提过的"本地未命中就联网重试"那类坑在这里天然不存在)。

为什么不是"人耳判断"的替代品:d-vector 是在英语语料(VoxCeleb)上训出来的,跨语言
（中文台词)的判别力没有正式验证过——2026-07-20 真机验证过一次:同角色(王六郎,5 段)
内部相似度均值 0.868,跨角色(王六郎 vs 许渔夫)均值 0.673,有明显区分度,说明这个代理
指标在这批素材上确实管用,但样本量小(2 个角色、7 段),不是"证明了这个指标永远可靠"。
拿它当"音色是否跟角色对得上"的第一道筛子,不是唯一判据——见
`hevi/assembly/native_dialogue.py::decide_dialogue_source` 的用法(阈值判定 + 显式
reason,不静默通过)。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_encoder: Any = None


class VoiceEmbedError(Exception):
    """音色向量计算失败。"""


def _ensure_encoder() -> Any:
    """懒加载 resemblyzer 的 VoiceEncoder(进程内单例,线程安全)。"""
    global _encoder
    if _encoder is not None:
        return _encoder
    with _lock:
        if _encoder is None:
            try:
                from resemblyzer import VoiceEncoder
            except ImportError as e:  # pragma: no cover - env guard
                raise VoiceEmbedError(f"voice_embed 需要 resemblyzer: {e}") from e
            logger.info("voice_embed: loading resemblyzer VoiceEncoder")
            _encoder = VoiceEncoder()
    return _encoder


def voice_embed(audio_path: Path | str) -> list[float]:
    """一段音频(wav,单声道)→ L2-归一化音色向量(list[float],256 维)。

    抛 VoiceEmbedError:文件不存在/resemblyzer 不可用/嵌入失败(比如整段都被内部 VAD
    判成静音,没有可用语音帧)。
    """
    p = Path(audio_path)
    if not p.exists():
        raise VoiceEmbedError(f"audio not found: {p}")
    try:
        from resemblyzer import preprocess_wav
    except ImportError as e:  # pragma: no cover
        raise VoiceEmbedError(f"voice_embed 需要 resemblyzer: {e}") from e

    encoder = _ensure_encoder()
    try:
        wav = preprocess_wav(p)
        return encoder.embed_utterance(wav).tolist()
    except Exception as e:
        raise VoiceEmbedError(f"embed failed for {p}: {e}") from e
