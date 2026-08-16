"""procedural_bgm —— 免费氛围 BGM 程序化合成(零素材、零模型、纯 numpy)。

hevi 的 bgm_library 只有目录框架,音频文件空缺 —— 这是全链路最大免费缺口。
本模块用合成器直接生成氛围垫:和弦 pad(带谐波的锯齿波 + 一阶低通)+ 根音 bass
+ 可选鼓组(kick/hat 由包络与噪声合成),按 mood 预设取和弦进行与节奏型。

关键优势:
  1. 零成本:不依赖任何音频库/素材/网络;
  2. 自带精确拍点:我们合成时就知道每个 beat 的时刻,直接产出 BeatGrid,
     供 beat_sync 钉切点(不需要 librosa 分析);
  3. 确定性:同参数必同输出(seed 固定),可回归测试。

输出 16-bit PCM WAV;mp3 转码交给 ffmpeg(调用方可选)。
"""

from __future__ import annotations

import json
import logging
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SR = 44100  # 采样率

# MIDI note → 频率(Hz)
_MIDI_FREQ: dict[int, float] = {n: 440.0 * 2.0 ** ((n - 69) / 12.0) for n in range(128)}


@dataclass(frozen=True)
class BeatGrid:
    """等距节拍网格(与 hevi.motion.beat_sync.BeatGrid 同构)。"""

    bpm: float
    t0: float
    period_s: float
    beat_count: int
    beat_times: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bpm": self.bpm,
            "t0": self.t0,
            "period_s": self.period_s,
            "beat_count": self.beat_count,
            "beat_times": self.beat_times,
        }


#: mood → (bpm, 和弦进行[每小节一个和弦,半音相对根音], 鼓型, 音色)
#: 和弦进行用小罗马和弦根音偏移 + 三和弦三音/五音偏移。
MOOD_PRESETS: dict[str, dict[str, Any]] = {
    # Am F C G 的温柔循环
    "calm": {
        "bpm": 70,
        "progression": [
            {"root": 0, "chord": (0, 3, 7)},    # Am
            {"root": -4, "chord": (0, 3, 7)},   # F
            {"root": -9, "chord": (0, 4, 7)},   # C
            {"root": -2, "chord": (0, 3, 7)},   # G
        ],
        "drums": "soft",
        "wave": "saw",
        "bass_octave": -1,
    },
    # C G Am F,明亮
    "bright": {
        "bpm": 100,
        "progression": [
            {"root": 0, "chord": (0, 4, 7)},
            {"root": -5, "chord": (0, 4, 7)},
            {"root": -3, "chord": (0, 3, 7)},
            {"root": -7, "chord": (0, 4, 7)},
        ],
        "drums": "pop",
        "wave": "tri",
        "bass_octave": -1,
    },
    # Am F C G 低音走,史诗感
    "epic": {
        "bpm": 90,
        "progression": [
            {"root": 0, "chord": (0, 3, 7)},
            {"root": -4, "chord": (0, 3, 7)},
            {"root": -9, "chord": (0, 4, 7)},
            {"root": -5, "chord": (0, 4, 7)},
        ],
        "drums": "cinematic",
        "wave": "saw",
        "bass_octave": -2,
    },
    # 小调 + 半音进行,紧张
    "tense": {
        "bpm": 110,
        "progression": [
            {"root": 0, "chord": (0, 3, 6)},    # Am
            {"root": 1, "chord": (0, 3, 6)},    # A#dim-ish
            {"root": 0, "chord": (0, 3, 6)},
            {"root": 8, "chord": (0, 3, 6)},    # F
        ],
        "drums": "hard",
        "wave": "saw",
        "bass_octave": -1,
    },
    # 温暖氛围(纪录/人文)
    "warm": {
        "bpm": 72,
        "progression": [
            {"root": 0, "chord": (0, 4, 7)},
            {"root": -3, "chord": (0, 3, 7)},
            {"root": 2, "chord": (0, 3, 7)},
            {"root": -4, "chord": (0, 4, 7)},
        ],
        "drums": "soft",
        "wave": "sine",
        "bass_octave": -1,
    },
}


@dataclass
class BgmConfig:
    """程序化 BGM 参数(确定性)。"""

    mood: str = "calm"
    bpm: int = 0  # 0 = 用 mood 预设
    duration_s: float = 16.0
    root_midi: int = 57  # A3(基调根音)
    gain: float = 0.32
    seed: int = 0
    with_drums: bool = True


def _preset(mood: str) -> dict[str, Any]:
    p = MOOD_PRESETS.get(mood)
    if p is None:
        raise ValueError(f"unknown mood {mood!r}; expected one of {', '.join(MOOD_PRESETS)}")
    return p


def _freq(midi: int) -> float:
    """MIDI 音符 → 频率;越界则夹紧。"""
    midi = max(21, min(108, midi))
    return _MIDI_FREQ[midi]


def _lowpass1(samples: np.ndarray, cutoff_hz: float, sr: int = SR) -> np.ndarray:
    """一阶 IIR 低通(单极)。alpha 由 cutoff 推导。"""
    dt = 1.0 / sr
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = dt / (rc + dt)
    out = np.empty_like(samples)
    acc = 0.0
    for i, x in enumerate(samples):
        acc += alpha * (x - acc)
        out[i] = acc
    return np.asarray(out)


def _wave(mode: str, phase: np.ndarray) -> np.ndarray:
    """振荡器:同一相位 → 不同波形。"""
    if mode == "sine":
        return np.asarray(np.sin(phase))
    if mode == "tri":
        return np.asarray(2.0 / math.pi * np.arcsin(np.sin(phase)))
    if mode == "saw":
        return np.asarray(2.0 * ((phase / (2.0 * math.pi)) % 1.0) - 1.0)
    # 默认 saw
    return np.asarray(2.0 * ((phase / (2.0 * math.pi)) % 1.0) - 1.0)


def _adsr_envelope(n: int, *, attack_s: float, release_s: float, sr: int = SR) -> np.ndarray:
    """ADSR 包络(无 sustain 段,attack 线性升,release 指数降)。"""
    env = np.ones(n, dtype=np.float64)
    a = int(attack_s * sr)
    if a > 0:
        env[:a] = np.linspace(0.0, 1.0, a)
    r = int(release_s * sr)
    if r > 0 and r < n:
        env[n - r:] = np.linspace(1.0, 0.0, r) ** 1.5
    return env


def _kick(sr: int = SR, dur_s: float = 0.35) -> np.ndarray:
    """底鼓:40→55Hz 正弦扫频 + 指数衰减。"""
    n = int(dur_s * sr)
    t = np.arange(n) / sr
    f = 45.0 + 25.0 * np.exp(-t * 18.0)
    phase = 2.0 * math.pi * np.cumsum(f) / sr
    return np.sin(phase) * np.exp(-t * 14.0) * 1.2


def _hat(sr: int = SR, dur_s: float = 0.06) -> np.ndarray:
    """踩镲:白噪声 + 高通(差分)+ 快衰减。"""
    rng = np.random.default_rng(42)
    n = int(dur_s * sr)
    noise = rng.standard_normal(n)
    hp = np.diff(noise, prepend=0.0)  # 一阶差分 = 简易高通
    return hp * np.exp(-np.arange(n) / sr / 0.015) * 0.5


def _snare(sr: int = SR, dur_s: float = 0.18) -> np.ndarray:
    """军鼓:噪声 + 200Hz 音调混合,快衰减。"""
    rng = np.random.default_rng(7)
    n = int(dur_s * sr)
    t = np.arange(n) / sr
    tone = np.sin(2.0 * math.pi * 190.0 * t) * np.exp(-t * 30.0)
    noise = rng.standard_normal(n) * np.exp(-t / 0.04)
    return (tone * 0.5 + noise * 0.6) * 0.6


def _drums_pattern(drums: str, bar: int, beat_in_bar: int, bpm: int) -> dict[str, float]:
    """返回该拍的鼓事件:{"kick": 1.0, "snare": 0.0, "hat": 0.7}。"""
    out: dict[str, float] = {"kick": 0.0, "snare": 0.0, "hat": 0.0}
    if drums == "soft":
        out["kick"] = 0.8 if beat_in_bar == 0 else (0.4 if beat_in_bar == 2 else 0.0)
        out["hat"] = 0.25 if beat_in_bar % 2 == 0 else 0.0
    elif drums == "pop":
        out["kick"] = 1.0 if beat_in_bar in (0, 2) else 0.0
        out["snare"] = 0.8 if beat_in_bar in (1, 3) else 0.0
        out["hat"] = 0.5
    elif drums == "cinematic":
        out["kick"] = 1.0 if beat_in_bar == 0 else 0.0
        out["kick"] += 0.7 if beat_in_bar == 2 else 0.0
    elif drums == "hard":
        out["kick"] = 1.0 if beat_in_bar in (0, 2) else 0.0
        out["snare"] = 0.9 if beat_in_bar in (1, 3) else 0.0
        out["hat"] = 0.7
    return out


def synthesize_bgm(config: BgmConfig) -> tuple[np.ndarray, BeatGrid]:
    """合成 BGM,返回 (混音波形 [n], BeatGrid 精确拍点)。"""
    preset = _preset(config.mood)
    bpm = config.bpm or int(preset["bpm"])
    wave_mode = preset["wave"]
    drums = preset["drums"]
    progression = preset["progression"]
    bass_oct = preset["bass_octave"]
    rng = np.random.default_rng(config.seed)

    beat_s = 60.0 / bpm
    bar_s = beat_s * 4
    n_bars = max(1, math.ceil(config.duration_s / bar_s))
    total_s = n_bars * bar_s
    n = int(total_s * SR) + SR  # 留 1s 尾音
    mix = np.zeros(n, dtype=np.float64)

    beat_times: list[float] = []
    t0 = beat_s * 0.5  # 前导半拍(录音机启动感)

    for bar in range(n_bars):
        bar_start = bar * bar_s
        chord = progression[bar % len(progression)]
        root = config.root_midi + chord["root"]
        notes = [root + d for d in chord["chord"]]
        # ── pad:和弦音符叠加(带泛音),整小节包络 ──
        for note in notes:
            freq = _freq(note)
            n_span = int(bar_s * SR)
            t = np.arange(n_span) / SR
            phase = 2.0 * math.pi * freq * t + rng.uniform(0, 2 * math.pi)
            tone = _wave(wave_mode, phase)
            # 两层泛音(soft):基频 1.0 + 八度 0.35 + 五度 0.2,过暖低通
            if wave_mode == "saw":
                tone = (
                    _wave("saw", phase) * 0.6
                    + _wave("saw", phase * 2.0) * 0.3
                    + _wave("saw", phase * 3.0) * 0.12
                )
                tone = _lowpass1(tone, 900.0)
            elif wave_mode == "tri":
                tone = _wave("tri", phase) * 0.8 + _wave("sine", phase * 2.0) * 0.25
                tone = _lowpass1(tone, 1600.0)
            else:
                tone = _lowpass1(tone, 700.0)
            env = _adsr_envelope(n_span, attack_s=bar_s * 0.35, release_s=bar_s * 0.4)
            seg = mix[int(bar_start * SR): int(bar_start * SR) + n_span]
            mix[int(bar_start * SR): int(bar_start * SR) + n_span] = seg + tone * env * 0.5
        # ── bass:根音低八度,半音符时值 ──
        bass_freq = _freq(root + bass_oct)
        n_bass = int(beat_s * 2 * SR)
        t_b = np.arange(n_bass) / SR
        bass = _wave("sine", 2.0 * math.pi * bass_freq * t_b)
        bass_env = _adsr_envelope(n_bass, attack_s=0.02, release_s=beat_s * 0.8)
        start = int((bar_start + beat_s * 0) * SR)
        mix[start: start + n_bass] += bass * bass_env * 0.55
        # ── 鼓组(每拍) ──
        if config.with_drums:
            for beat in range(4):
                b_time = bar_start + beat * beat_s
                ev = _drums_pattern(drums, bar, beat, bpm)
                pos = int(b_time * SR)
                if ev["kick"] > 0:
                    k = _kick() * ev["kick"]
                    mix[pos: pos + len(k)] += k
                if ev["snare"] > 0:
                    s = _snare() * ev["snare"]
                    mix[pos: pos + len(s)] += s
                if ev["hat"] > 0:
                    h = _hat() * ev["hat"]
                    mix[pos: pos + len(h)] += h
                beat_times.append(b_time)
        else:
            beat_times.extend(bar_start + beat * beat_s for beat in range(4))

    # 全局包络:首尾各 1s 淡入淡出 + 归一化到 gain
    n_used = int(total_s * SR)
    mix = mix[:n_used]
    fade = np.ones(n_used)
    f = int(SR * 1.0)
    fade[:f] = np.linspace(0.0, 1.0, f) ** 1.5
    fade[-f:] = np.linspace(1.0, 0.0, f) ** 1.5
    mix = mix * fade
    peak = float(np.max(np.abs(mix))) or 1.0
    mix = mix / peak * config.gain
    return mix, BeatGrid(
        bpm=float(bpm),
        t0=t0,
        period_s=beat_s,
        beat_count=len(beat_times),
        beat_times=beat_times,
    )


def write_wav(samples: np.ndarray, out_path: Path | str, sr: int = SR) -> Path:
    """16-bit PCM WAV 落盘。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm16.tobytes())
    return out_path


def generate_bgm_file(config: BgmConfig, out_path: Path | str) -> tuple[Path, BeatGrid]:
    """完整入口:合成 + 落盘 WAV,返回 (path, beat_grid)。"""
    samples, grid = synthesize_bgm(config)
    written = write_wav(samples, out_path)
    return written, grid


def render_bgm_plan(config: BgmConfig, output_dir: Path) -> dict[str, Any]:
    """3O 风格报告入口:合成 + 落盘 + beat grid JSON。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path, grid = generate_bgm_file(config, output_dir / "bgm.wav")
    grid_path = output_dir / "bgm_beats.json"
    grid_path.write_text(json.dumps(grid.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "completed",
        "bgm_path": str(wav_path),
        "beats_path": str(grid_path),
        "duration_s": round(len(np.fromfile(wav_path, dtype=np.int16)) / SR, 2)
        if wav_path.exists()
        else 0.0,
        "beat_grid": grid.to_dict(),
    }


__all__ = [
    "MOOD_PRESETS",
    "BeatGrid",
    "BgmConfig",
    "generate_bgm_file",
    "render_bgm_plan",
    "synthesize_bgm",
    "write_wav",
]
