"""生成占位音效(SFX)—— 纯 Python 合成(无需 ffmpeg),点亮音效混音链路。

不是版权音效,是程序合成的短促提示音(噪声包络/正弦扫频),让 assemble_longvideo 的
音效叠加有真实可解码音频可用。以后有正式音效库直接放同名前缀文件到 assets/audio/sfx/
即可(BGMLibrary.get_sfx 按文件名前缀匹配),代码不用改。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100


def _envelope(n: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(n)
    a = int(n * attack)
    r = int(n * release)
    if a > 0:
        env[:a] = np.linspace(0, 1, a)
    if r > 0:
        env[-r:] = np.linspace(1, 0, r)
    return env


def whoosh(dur: float = 0.8) -> np.ndarray:
    """噪声扫频:低通截止频率随时间上升再下降,模拟"呼"一声划过。"""
    n = int(SR * dur)
    noise = np.random.default_rng(42).normal(0, 1, n)
    t = np.linspace(0, 1, n)
    cutoff = 200 + 4000 * np.sin(np.pi * t)  # 上升再下降
    # 简易一阶低通(逐样本 IIR),截止频率随时间变化
    out = np.zeros(n)
    prev = 0.0
    for i in range(n):
        alpha = 1.0 - np.exp(-2 * np.pi * cutoff[i] / SR)
        prev = prev + alpha * (noise[i] - prev)
        out[i] = prev
    out *= _envelope(n, 0.1, 0.5)
    return out * 0.5


def ding(dur: float = 0.6) -> np.ndarray:
    """正弦+泛音衰减,类提示音"叮"。"""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    decay = np.exp(-4 * t)
    out = (np.sin(2 * np.pi * 880 * t) + 0.4 * np.sin(2 * np.pi * 1760 * t)) * decay
    return out * 0.4


def impact(dur: float = 0.4) -> np.ndarray:
    """低频冲击 + 噪声爆发,类"砰"。"""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    thump = np.sin(2 * np.pi * 60 * t) * np.exp(-15 * t)
    noise = np.random.default_rng(7).normal(0, 1, n) * np.exp(-25 * t)
    return (thump * 0.8 + noise * 0.3) * 0.6


def pop(dur: float = 0.15) -> np.ndarray:
    """短促正弦衰减,类"啵"。"""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    out = np.sin(2 * np.pi * 1200 * t) * np.exp(-30 * t)
    return out * 0.45


def chime(dur: float = 1.0) -> np.ndarray:
    """三音符上行琶音,类"叮铃"过场提示。"""
    n = int(SR * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    out = np.zeros(n)
    for i, f in enumerate((523.25, 659.25, 783.99)):  # C5 E5 G5
        start = int(n * i / 3)
        seg = t[start:] - t[start]
        decay = np.exp(-3 * seg)
        out[start:] += np.sin(2 * np.pi * f * seg) * decay * 0.35
    return np.clip(out, -1, 1) * 0.5


GENERATORS = {"whoosh": whoosh, "ding": ding, "impact": impact, "pop": pop, "chime": chime}


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "assets" / "audio" / "sfx"
    for name, gen in GENERATORS.items():
        p = root / f"{name}.wav"
        write_wav(p, gen())
        print(f"{name}: {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
