"""副语言标签解析（对标 VoiceBox Chatterbox Turbo 的 paralinguistic tags）。

支持在文本中嵌入标签，在 TTS 合成时转换为对应的音频效果：
- [laugh] / [chuckle] — 笑声
- [sigh] / [groan] — 叹息
- [gasp] — 倒吸一口气
- [cough] — 咳嗽
- [sniff] — 吸鼻子
- [shush] — 嘘声
- [clear_throat] — 清嗓子
- [pause:1.5] — 停顿 1.5 秒
- [whisper]...[/whisper] — 低语区间
- [shout]...[/shout] — 喊叫区间

标签格式: [tag_name] 或 [tag_name:param]
区间标签: [tag]...text...[/tag]
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class ParaTag:
    """副语言标签。"""
    tag_type: str  # laugh, sigh, gasp, pause, whisper, shout, etc.
    param: str = ""  # 可选参数（如 pause 的时长）
    is_open: bool = True  # 区间标签的开始 vs 结束
    position: int = 0  # 在文本中的位置


@dataclass
class TaggedSegment:
    """带标签的文本段。"""
    text: str
    tags: list[ParaTag] = field(default_factory=list)
    style_override: dict[str, Any] = field(default_factory=dict)


# ── 标签正则 ────────────────────────────────────────────────────────────────

_TAG_PATTERN = re.compile(
    r'\[(\w+)(?::([^]]+))?\]'  # [tag] or [tag:param]
    r'|'
    r'\[/(\w+)\]'  # [/tag]
)


def parse_tags(text: str) -> list[tuple[str, list[ParaTag]]]:
    """解析文本中的副语言标签。

    Returns:
        [(text_segment, tags_before_it), ...] 的列表
    """
    segments: list[tuple[str, list[ParaTag]]] = []
    current_tags: list[ParaTag] = []
    last_end = 0

    for match in _TAG_PATTERN.finditer(text):
        start = match.start()
        # 添加标签前的文本段
        if start > last_end:
            segments.append((text[last_end:start], current_tags.copy()))
            current_tags.clear()

        if match.group(3):
            # 关闭标签 [/tag]
            current_tags.append(ParaTag(
                tag_type=match.group(3),
                is_open=False,
                position=start,
            ))
        else:
            # 开始标签 [tag] or [tag:param]
            current_tags.append(ParaTag(
                tag_type=match.group(1),
                param=match.group(2) or "",
                is_open=True,
                position=start,
            ))

        last_end = match.end()

    # 剩余文本
    if last_end < len(text):
        segments.append((text[last_end:], current_tags))
    elif current_tags:
        segments.append(("", current_tags))

    return segments


def strip_tags(text: str) -> str:
    """移除所有副语言标签，返回纯文本。"""
    return _TAG_PATTERN.sub("", text)


def extract_text_segments(text: str) -> list[str]:
    """提取纯文本段（跳过标签）。"""
    return [seg for seg, _ in parse_tags(text) if seg.strip()]


# ── 标签音频生成 ────────────────────────────────────────────────────────────

def _generate_noise(duration_s: float, sr: int, amplitude: float = 0.3) -> np.ndarray:
    """生成白噪声。"""
    samples = int(sr * duration_s)
    return np.random.randn(samples) * amplitude


def _generate_laugh(sr: int, duration_s: float = 0.6) -> np.ndarray:
    """生成笑声音频（脉冲式噪声 bursts）。"""
    total_samples = int(sr * duration_s)
    audio = np.zeros(total_samples, dtype=np.float32)
    burst_len = int(sr * 0.08)  # 80ms per burst
    gap_len = int(sr * 0.04)  # 40ms gap

    pos = 0
    while pos + burst_len < total_samples:
        burst = _generate_noise(burst_len / sr, sr, 0.4)
        # 包络：快速攻击，指数衰减
        envelope = np.exp(-np.arange(burst_len) / (burst_len * 0.5))
        burst *= envelope
        audio[pos:pos + burst_len] += burst
        pos += burst_len + gap_len

    return np.clip(audio, -1, 1)


def _generate_sigh(sr: int, duration_s: float = 0.8) -> np.ndarray:
    """生成叹息音频（下行扫频 + 噪声）。"""
    total_samples = int(sr * duration_s)
    t = np.arange(total_samples) / sr
    # 下行扫频 400Hz → 150Hz
    freq = 400 - 250 * (t / duration_s)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase) * 0.3
    noise = _generate_noise(duration_s, sr, 0.15)
    # 包络
    envelope = np.sin(np.pi * t / duration_s) * np.exp(-t / (duration_s * 0.8))
    return np.clip((tone + noise) * envelope, -1, 1)


def _generate_gasp(sr: int, duration_s: float = 0.3) -> np.ndarray:
    """生成倒吸气音频（短促噪声 + 上行扫频）。"""
    total_samples = int(sr * duration_s)
    t = np.arange(total_samples) / sr
    freq = 800 + 1200 * (t / duration_s)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase) * 0.25
    noise = _generate_noise(duration_s, sr, 0.2)
    envelope = np.exp(-((t - duration_s * 0.3) ** 2) / (2 * (duration_s * 0.15) ** 2))
    return np.clip((tone + noise) * envelope, -1, 1)


def _generate_cough(sr: int, duration_s: float = 0.25) -> np.ndarray:
    """生成咳嗽音频（短脉冲噪声）。"""
    total_samples = int(sr * duration_s)
    audio = _generate_noise(duration_s, sr, 0.5)
    envelope = np.exp(-np.arange(total_samples) / (total_samples * 0.3))
    return np.clip(audio * envelope, -1, 1)


def _generate_sniff(sr: int, duration_s: float = 0.2) -> np.ndarray:
    """生成吸鼻子音频。"""
    total_samples = int(sr * duration_s)
    t = np.arange(total_samples) / sr
    freq = 2000 + 500 * np.sin(2 * np.pi * 8 * t)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase) * 0.2
    noise = _generate_noise(duration_s, sr, 0.15)
    envelope = np.exp(-np.arange(total_samples) / (total_samples * 0.5))
    return np.clip((tone + noise) * envelope, -1, 1)


def _generate_shush(sr: int, duration_s: float = 0.4) -> np.ndarray:
    """生成嘘声音频（带通噪声）。"""
    total_samples = int(sr * duration_s)
    from scipy.signal import butter, sosfilt
    noise = _generate_noise(duration_s, sr, 0.35)
    # 带通 2000-6000 Hz
    sos_hi = butter(2, [2000 / (sr / 2), 6000 / (sr / 2)], btype='band', output='sos')
    filtered = sosfilt(sos_hi, noise)
    envelope = np.sin(np.pi * np.arange(total_samples) / total_samples)
    return np.clip(filtered * envelope, -1, 1)


def _generate_clear_throat(sr: int, duration_s: float = 0.3) -> np.ndarray:
    """生成清嗓子音频。"""
    total_samples = int(sr * duration_s)
    t = np.arange(total_samples) / sr
    freq = 300 + 100 * np.sin(2 * np.pi * 12 * t)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    tone = np.sin(phase) * 0.3
    noise = _generate_noise(duration_s, sr, 0.25)
    envelope = np.exp(-((t - 0.1) ** 2) / (2 * 0.05 ** 2))
    return np.clip((tone + noise) * envelope, -1, 1)


# ── 标签音频注册表 ──────────────────────────────────────────────────────────

_TAG_AUDIO_GENERATORS: dict[str, Any] = {
    "laugh": _generate_laugh,
    "chuckle": lambda sr: _generate_laugh(sr, 0.4),
    "sigh": _generate_sigh,
    "groan": lambda sr: _generate_sigh(sr, 1.0),
    "gasp": _generate_gasp,
    "cough": _generate_cough,
    "sniff": _generate_sniff,
    "shush": _generate_shush,
    "clear_throat": _generate_clear_throat,
}


def generate_tag_audio(tag_type: str, sr: int = 44100) -> np.ndarray:
    """为指定标签生成音频。"""
    gen = _TAG_AUDIO_GENERATORS.get(tag_type)
    if gen is None:
        logger.warning("no audio generator for tag: %s", tag_type)
        return np.zeros(int(sr * 0.1), dtype=np.float32)  # 100ms silence
    return gen(sr)


def get_style_override(tag_type: str) -> dict[str, Any]:
    """获取标签对应的 TTS 风格覆盖参数。"""
    overrides: dict[str, dict[str, Any]] = {
        "whisper": {"rate": 0.7, "pitch": -2, "volume": 0.4},
        "shout": {"rate": 1.2, "pitch": 3, "volume": 1.5},
        "laugh": {"rate": 1.1, "pitch": 2},
        "sigh": {"rate": 0.8, "pitch": -3},
    }
    return overrides.get(tag_type, {})


def apply_paralinguistic_to_audio(
    text: str,
    base_audio: np.ndarray,
    sr: int,
    tts_fn: Any = None,
) -> np.ndarray:
    """将副语言标签应用到基础音频上。

    在 TTS 合成后的音频中，根据标签位置插入对应的音效。

    Args:
        text: 原始文本（含标签）
        base_audio: TTS 合成的基础音频
        sr: 采样率
        tts_fn: 可选的 TTS 函数，用于生成 whisper/shout 区间的变体

    Returns:
        混合后的音频
    """
    segments = parse_tags(text)
    if not segments:
        return base_audio

    # 简单策略：在音频开头/中间插入标签音效
    # 精确的时间对齐需要 TTS 引擎提供 word-level timestamps
    parts: list[np.ndarray] = [base_audio]

    for seg_text, tags in segments:
        for tag in tags:
            if not tag.is_open:
                continue
            if tag.tag_type == "pause":
                pause_s = float(tag.param) if tag.param else 0.5
                parts.append(np.zeros(int(sr * pause_s), dtype=np.float32))
            elif tag.tag_type in _TAG_AUDIO_GENERATORS:
                tag_audio = generate_tag_audio(tag.tag_type, sr)
                parts.append(tag_audio)

    if len(parts) == 1:
        return base_audio

    # 拼接：基础音频 + 标签音效（简单追加）
    return np.concatenate(parts)
