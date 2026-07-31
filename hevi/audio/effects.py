"""音频后处理效果链（对标 VoiceBox 的 Post-Processing Effects）。

提供 8 种音频效果处理器，可组合成效果链：
- Pitch Shift — 音调偏移（±12 半音）
- Reverb — 混响（房间大小、阻尼、干湿比）
- Delay — 延迟/回声（时间、反馈、混合比）
- Chorus — 合唱/镶边
- Compressor — 动态范围压缩
- Gain — 音量调整（-40 到 +40 dB）
- High-Pass Filter — 高通滤波
- Low-Pass Filter — 低通滤波

使用纯 numpy/scipy 实现，无需额外依赖。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class EffectConfig:
    """效果器配置。"""
    effect_type: Literal["pitch_shift", "reverb", "delay", "chorus",
                         "compressor", "gain", "highpass", "lowpass"]
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class EffectsChain:
    """效果链：多个效果器按顺序应用。"""
    effects: list[EffectConfig] = field(default_factory=list)
    sample_rate: int = 44100

    def add(self, effect_type: str, **params: Any) -> EffectsChain:
        """添加效果器到链尾。"""
        self.effects.append(EffectConfig(effect_type=effect_type, params=params))
        return self

    def apply(self, audio: np.ndarray, sample_rate: int | None = None) -> np.ndarray:
        """应用整个效果链。"""
        sr = sample_rate or self.sample_rate
        result = audio.copy()
        for cfg in self.effects:
            if not cfg.enabled:
                continue
            fn = _EFFECT_REGISTRY.get(cfg.effect_type)
            if fn is None:
                logger.warning("unknown effect: %s", cfg.effect_type)
                continue
            result = fn(result, sr, **cfg.params)
        return result


# ── 预置效果链 ──────────────────────────────────────────────────────────────

def preset_robotic() -> EffectsChain:
    """机器人效果：pitch up + chorus + compressor。"""
    return EffectsChain() \
        .add("pitch_shift", semitones=3) \
        .add("chorus", rate_hz=4.0, depth_ms=3.0, mix=0.5) \
        .add("compressor", threshold_db=-20, ratio=6.0)


def preset_radio() -> EffectsChain:
    """广播/电话效果：bandpass + compressor + gain。"""
    return EffectsChain() \
        .add("highpass", cutoff_hz=300) \
        .add("lowpass", cutoff_hz=3400) \
        .add("compressor", threshold_db=-15, ratio=4.0) \
        .add("gain", db=3.0)


def preset_echo_chamber() -> EffectsChain:
    """大厅回声：长 delay + reverb。"""
    return EffectsChain() \
        .add("delay", delay_ms=300, feedback=0.4, mix=0.3) \
        .add("reverb", room_size=0.8, damping=0.5, mix=0.4)


def preset_deep_voice() -> EffectsChain:
    """低沉嗓音：pitch down + compressor。"""
    return EffectsChain() \
        .add("pitch_shift", semitones=-3) \
        .add("compressor", threshold_db=-18, ratio=3.0) \
        .add("gain", db=2.0)


def preset_cave() -> EffectsChain:
    """山洞/洞穴效果：大混响 + 长 delay。"""
    return EffectsChain() \
        .add("reverb", room_size=0.9, damping=0.3, mix=0.5) \
        .add("delay", delay_ms=200, feedback=0.5, mix=0.2)


def preset_phone_call() -> EffectsChain:
    """电话通话效果：窄带通 + 压缩。"""
    return EffectsChain() \
        .add("highpass", cutoff_hz=400) \
        .add("lowpass", cutoff_hz=3000) \
        .add("compressor", threshold_db=-12, ratio=5.0) \
        .add("gain", db=4.0)


PRESETS: dict[str, Any] = {
    "robotic": preset_robotic,
    "radio": preset_radio,
    "echo_chamber": preset_echo_chamber,
    "deep_voice": preset_deep_voice,
    "cave": preset_cave,
    "phone_call": preset_phone_call,
}


# ── 单个效果器实现 ──────────────────────────────────────────────────────────

def pitch_shift(
    audio: np.ndarray, sr: int,
    semitones: float = 0.0,
    **_: Any,
) -> np.ndarray:
    """音调偏移（使用相位声码器）。"""
    if abs(semitones) < 0.01:
        return audio.copy()

    # 确保 mono
    is_stereo = audio.ndim == 2
    if is_stereo:
        left = _pitch_shift_mono(audio[:, 0], sr, semitones)
        right = _pitch_shift_mono(audio[:, 1], sr, semitones)
        return np.column_stack([left, right])
    return _pitch_shift_mono(audio, sr, semitones)


def _pitch_shift_mono(audio: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Mono pitch shift using phase vocoder."""
    import numpy as np

    # 使用 librosa if available, else simple resample approach
    try:
        import librosa
        return librosa.effects.pitch_shift(audio.astype(np.float32), sr=sr, n_steps=semitones)
    except ImportError:
        # Fallback: resample trick (changes duration but preserves pitch ratio)
        rate = 2 ** (semitones / 12.0)
        indices = np.arange(0, len(audio), rate)
        indices = indices[indices < len(audio)].astype(int)
        resampled = audio[indices]
        # Resample back to original length
        from scipy.signal import resample
        return resample(resampled, len(audio)).astype(audio.dtype)


def reverb(
    audio: np.ndarray, sr: int,
    room_size: float = 0.5,
    damping: float = 0.5,
    mix: float = 0.3,
    **_: Any,
) -> np.ndarray:
    """混响效果（简单 FDN 混响器）。"""
    is_stereo = audio.ndim == 2
    mono = audio[:, 0] if is_stereo else audio

    # 简单混响：多个延迟线叠加
    delay_times_ms = [29, 37, 41, 43, 47, 53]  # 质数延迟避免共振
    gains = [0.7, 0.6, 0.55, 0.5, 0.45, 0.4]

    reverb_signal = np.zeros(len(mono), dtype=np.float64)
    for delay_ms, gain in zip(delay_times_ms, gains):
        delay_samples = int(sr * delay_ms / 1000 * (0.5 + room_size))
        damped_gain = gain * (1.0 - damping * 0.5)
        if delay_samples < len(mono):
            reverb_signal[delay_samples:] += mono[:-delay_samples] * damped_gain

    # 二次反射
    for delay_ms, gain in zip(delay_times_ms[:3], gains[:3]):
        delay_samples = int(sr * delay_ms / 1000 * (1.0 + room_size)) * 2
        if delay_samples < len(mono):
            reverb_signal[delay_samples:] += mono[:-delay_samples] * gain * 0.3

    mixed = mono * (1 - mix) + reverb_signal * mix
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak * 0.95

    if is_stereo:
        return np.column_stack([mixed, mixed * 0.98 + reverb_signal * 0.02])
    return mixed.astype(audio.dtype)


def delay(
    audio: np.ndarray, sr: int,
    delay_ms: float = 250.0,
    feedback: float = 0.3,
    mix: float = 0.3,
    **_: Any,
) -> np.ndarray:
    """延迟/回声效果。"""
    is_stereo = audio.ndim == 2
    mono = audio[:, 0] if is_stereo else audio

    delay_samples = int(sr * delay_ms / 1000)
    output = mono.astype(np.float64).copy()

    if delay_samples < len(output):
        for echo_idx in range(1, 8):  # 最多 8 次回声
            offset = delay_samples * echo_idx
            if offset >= len(output):
                break
            echo_gain = feedback ** echo_idx
            end = min(len(output), offset + len(mono))
            output[offset:end] += mono[:end - offset] * echo_gain

    mixed = mono * (1 - mix) + output * mix
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak * 0.95

    if is_stereo:
        return np.column_stack([mixed, mixed])
    return mixed.astype(audio.dtype)


def chorus(
    audio: np.ndarray, sr: int,
    rate_hz: float = 1.5,
    depth_ms: float = 5.0,
    mix: float = 0.4,
    **_: Any,
) -> np.ndarray:
    """合唱/镶边效果。"""
    is_stereo = audio.ndim == 2
    mono = audio[:, 0] if is_stereo else audio

    t = np.arange(len(mono)) / sr
    # LFO 调制延迟时间
    mod = (1 + np.sin(2 * np.pi * rate_hz * t)) / 2
    delay_samples = (mod * depth_ms * sr / 1000).astype(int)

    output = np.zeros(len(mono), dtype=np.float64)
    for i in range(len(mono)):
        d = delay_samples[i]
        if d > 0 and i - d >= 0:
            output[i] = mono[i - d]
        else:
            output[i] = mono[i]

    mixed = mono * (1 - mix) + output * mix
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak * 0.95

    if is_stereo:
        return np.column_stack([mixed, mixed])
    return mixed.astype(audio.dtype)


def compressor(
    audio: np.ndarray, sr: int,
    threshold_db: float = -20.0,
    ratio: float = 4.0,
    attack_ms: float = 10.0,
    release_ms: float = 100.0,
    **_: Any,
) -> np.ndarray:
    """动态范围压缩。"""
    is_stereo = audio.ndim == 2
    mono = audio[:, 0].astype(np.float64) if is_stereo else audio.astype(np.float64)

    threshold_linear = 10 ** (threshold_db / 20.0)
    attack_coeff = np.exp(-1.0 / (sr * attack_ms / 1000))
    release_coeff = np.exp(-1.0 / (sr * release_ms / 1000))

    output = np.zeros(len(mono), dtype=np.float64)
    envelope = 0.0

    for i in range(len(mono)):
        level = abs(mono[i])
        if level > envelope:
            envelope = attack_coeff * envelope + (1 - attack_coeff) * level
        else:
            envelope = release_coeff * envelope + (1 - release_coeff) * level

        if envelope > threshold_linear:
            gain = threshold_linear + (envelope - threshold_linear) / ratio
            gain_factor = gain / max(envelope, 1e-10)
        else:
            gain_factor = 1.0

        output[i] = mono[i] * gain_factor

    peak = np.max(np.abs(output))
    if peak > 1.0:
        output = output / peak * 0.95

    if is_stereo:
        return np.column_stack([output, output])
    return output.astype(audio.dtype)


def gain_adjust(
    audio: np.ndarray, sr: int,
    db: float = 0.0,
    **_: Any,
) -> np.ndarray:
    """音量调整（dB）。"""
    factor = 10 ** (db / 20.0)
    result = audio * factor
    # Soft clip
    peak = np.max(np.abs(result))
    if peak > 1.0:
        result = np.tanh(result)
    return result.astype(audio.dtype)


def highpass_filter(
    audio: np.ndarray, sr: int,
    cutoff_hz: float = 200.0,
    order: int = 4,
    **_: Any,
) -> np.ndarray:
    """高通滤波。"""
    from scipy.signal import butter, sosfilt
    nyq = sr / 2
    cutoff = min(cutoff_hz, nyq * 0.99)
    sos = butter(order, cutoff / nyq, btype='high', output='sos')

    is_stereo = audio.ndim == 2
    if is_stereo:
        left = sosfilt(sos, audio[:, 0]).astype(audio.dtype)
        right = sosfilt(sos, audio[:, 1]).astype(audio.dtype)
        return np.column_stack([left, right])
    return sosfilt(sos, audio).astype(audio.dtype)


def lowpass_filter(
    audio: np.ndarray, sr: int,
    cutoff_hz: float = 5000.0,
    order: int = 4,
    **_: Any,
) -> np.ndarray:
    """低通滤波。"""
    from scipy.signal import butter, sosfilt
    nyq = sr / 2
    cutoff = min(cutoff_hz, nyq * 0.99)
    sos = butter(order, cutoff / nyq, btype='low', output='sos')

    is_stereo = audio.ndim == 2
    if is_stereo:
        left = sosfilt(sos, audio[:, 0]).astype(audio.dtype)
        right = sosfilt(sos, audio[:, 1]).astype(audio.dtype)
        return np.column_stack([left, right])
    return sosfilt(sos, audio).astype(audio.dtype)


# ── 效果器注册表 ────────────────────────────────────────────────────────────

_EFFECT_REGISTRY: dict[str, Any] = {
    "pitch_shift": pitch_shift,
    "reverb": reverb,
    "delay": delay,
    "chorus": chorus,
    "compressor": compressor,
    "gain": gain_adjust,
    "highpass": highpass_filter,
    "lowpass": lowpass_filter,
}


# ── 便捷函数 ────────────────────────────────────────────────────────────────

def apply_effects(
    input_path: Path,
    output_path: Path,
    chain: EffectsChain | None = None,
    preset: str | None = None,
) -> Path:
    """对音频文件应用效果链。

    Args:
        input_path: 输入音频文件
        output_path: 输出音频文件
        chain: 自定义效果链（优先于 preset）
        preset: 预置效果链名称

    Returns:
        输出文件路径
    """
    audio, sr = sf.read(str(input_path), dtype='float32')

    if chain is None and preset is not None:
        factory = PRESETS.get(preset)
        if factory is None:
            raise ValueError(f"unknown preset: {preset}. Available: {list(PRESETS.keys())}")
        chain = factory()

    if chain is None:
        chain = EffectsChain()

    processed = chain.apply(audio, sr)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), processed, sr)
    logger.info("applied effects: %s → %s", input_path, output_path)
    return output_path


def apply_effects_to_array(
    audio: np.ndarray,
    sr: int,
    chain: EffectsChain | None = None,
    preset: str | None = None,
) -> np.ndarray:
    """对 numpy 数组应用效果链。"""
    if chain is None and preset is not None:
        factory = PRESETS.get(preset)
        if factory is None:
            raise ValueError(f"unknown preset: {preset}")
        chain = factory()
    if chain is None:
        return audio.copy()
    return chain.apply(audio, sr)


def list_presets() -> list[str]:
    """列出可用预置效果链。"""
    return sorted(PRESETS.keys())
