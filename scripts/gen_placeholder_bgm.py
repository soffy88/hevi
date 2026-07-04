"""生成占位 BGM —— 纯 Python 合成(无需 ffmpeg),按情绪给和声基调点亮 BGM 链路。

不是版权音乐,是程序合成的氛围底噪(和弦柱 + 包络),让 assemble_longvideo 的
ducking 混音链有真实可解码音频可用。以后有正式曲库直接替换同目录文件即可,
代码不用改(BGMLibrary.select_bgm 按文件名排序取首支)。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
DUR = 24.0  # 24s 循环底噪,装配器按成片时长自动 loop/截断(amix duration=longest 由旁白定)

# 情绪 → (根音 Hz, 和弦音程比例, 波形谐波权重, 颤音速度, 整体电平)
MOODS: dict[str, dict] = {
    "warm": dict(
        root=196.0,
        intervals=(1.0, 1.25, 1.5),
        harmonics=(1.0, 0.4, 0.15),
        vibrato_hz=3.0,
        gain=0.18,
    ),
    "upbeat": dict(
        root=261.6,
        intervals=(1.0, 1.25, 1.5, 2.0),
        harmonics=(1.0, 0.5, 0.3, 0.15),
        vibrato_hz=5.5,
        gain=0.16,
    ),
    "tense": dict(
        root=110.0,
        intervals=(1.0, 1.0595, 1.4142),
        harmonics=(1.0, 0.6, 0.35),
        vibrato_hz=7.0,
        gain=0.15,
    ),
    "epic": dict(
        root=98.0,
        intervals=(1.0, 1.5, 2.0, 3.0),
        harmonics=(1.0, 0.55, 0.35, 0.2),
        vibrato_hz=2.0,
        gain=0.22,
    ),
    "mystery": dict(
        root=146.8,
        intervals=(1.0, 1.1892, 1.4983),
        harmonics=(1.0, 0.3, 0.2),
        vibrato_hz=1.2,
        gain=0.14,
    ),
}


def synth(mood: str, cfg: dict) -> np.ndarray:
    t = np.linspace(0, DUR, int(SR * DUR), endpoint=False)
    out = np.zeros_like(t)
    vibrato = 1.0 + 0.006 * np.sin(2 * np.pi * cfg["vibrato_hz"] * t)
    for interval in cfg["intervals"]:
        freq = cfg["root"] * interval * vibrato
        for h_idx, h_w in enumerate(cfg["harmonics"], start=1):
            out += h_w * np.sin(2 * np.pi * freq * h_idx * t)
    out /= len(cfg["intervals"])
    # 呼吸感包络:慢 LFO 幅度调制,避免死板持续音
    breath = 0.75 + 0.25 * np.sin(2 * np.pi * 0.12 * t)
    out *= breath
    # 首尾淡入淡出,循环不炸音
    fade = int(SR * 1.5)
    env = np.ones_like(out)
    env[:fade] = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    out *= env * cfg["gain"]
    return np.clip(out, -1.0, 1.0)


def write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "assets" / "audio" / "bgm"
    for mood, cfg in MOODS.items():
        p = root / mood / "a_generated_pad.wav"
        write_wav(p, synth(mood, cfg))
        print(f"{mood}: {p} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
