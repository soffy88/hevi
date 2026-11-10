"""逐拍时钟：音乐分析 → beats.json；无音乐时用 TTS 时长生成虚拟拍点。

所有动画时间都从拍点取，渲染器不再自己猜时间。
"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SAMPLE_RATE = 22050
HOP = 512
FRAME = 1024


def ffprobe_duration(path: str | Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


def _decode(path: str | Path) -> np.ndarray:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg decode failed: {proc.stderr.decode('utf-8', 'ignore')[:400]}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _onset_envelope(samples: np.ndarray) -> tuple[np.ndarray, float]:
    if samples.size < FRAME * 2:
        return np.zeros(1, dtype=np.float32), 0.0
    n = 1 + (samples.size - FRAME) // HOP
    rms = np.empty(n, dtype=np.float32)
    for i in range(n):
        chunk = samples[i * HOP : i * HOP + FRAME]
        rms[i] = float(np.sqrt(np.mean(chunk * chunk) + 1e-12))
    onset = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    return onset, HOP / SAMPLE_RATE


def analyze_music(path: str | Path) -> dict[str, Any]:
    """BPM、首拍、每拍时间、每小节能量。纯 numpy，无需 librosa。"""
    samples = _decode(path)
    onset, hop_s = _onset_envelope(samples)
    duration = samples.size / SAMPLE_RATE
    if onset.size < 8 or float(onset.max()) <= 0:
        return {
            "bpm": 120.0,
            "first_beat_s": 0.0,
            "beat_s": 0.5,
            "beats": virtual_beats(duration, 120.0),
            "energy_per_bar": [],
            "duration_s": round(duration, 3),
            "source": "estimate",
        }
    centered = onset - float(onset.mean())
    corr = np.correlate(centered, centered, mode="full")[centered.size - 1 :]
    min_lag = max(1, int(60.0 / 180.0 / hop_s))
    max_lag = min(corr.size - 1, int(60.0 / 60.0 / hop_s))
    if max_lag <= min_lag:
        bpm = 120.0
    else:
        lag = int(np.argmax(corr[min_lag:max_lag]) + min_lag)
        bpm = 60.0 / (lag * hop_s)
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
    beat_s = 60.0 / bpm
    # 首拍：第一个显著 onset 峰。
    threshold = float(onset.mean() + onset.std())
    peaks = np.where(onset >= threshold)[0]
    first = float(peaks[0] * hop_s) if peaks.size else 0.0
    first = first % beat_s
    beats = [round(first + i * beat_s, 4) for i in range(int((duration - first) / beat_s) + 1)]
    energy: list[float] = []
    for i in range(0, max(1, len(beats) - 1), 4):
        a = int(beats[i] / hop_s)
        b = int(beats[min(i + 4, len(beats) - 1)] / hop_s) + 1
        energy.append(round(float(onset[a:b].sum()), 4))
    return {
        "bpm": round(bpm, 2),
        "first_beat_s": round(first, 4),
        "beat_s": round(beat_s, 4),
        "beats": beats,
        "energy_per_bar": energy,
        "duration_s": round(duration, 3),
        "source": "measured",
    }


def virtual_beats(total_s: float, bpm: float = 120.0) -> list[float]:
    beat_s = 60.0 / bpm
    count = max(2, math.ceil(total_s / beat_s) + 1)
    return [round(i * beat_s, 4) for i in range(count)]


def build_grid(duration_s: float, *, bpm: float = 120.0, first_beat_s: float = 0.0) -> list[float]:
    beat_s = 60.0 / bpm
    if duration_s <= 0:
        return [0.0]
    count = math.floor((duration_s - first_beat_s) / beat_s) + 1
    return [round(first_beat_s + i * beat_s, 4) for i in range(max(1, count))]


@dataclass
class Beat:
    index: int
    bar: int
    beat: int
    t: float
    duration: float
    shot_id: str
    visual: str
    big: str
    small: str
    sfx: str
    narration: str
    energy: float
    focus: str = ""
    params: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "bar": self.bar,
            "beat": self.beat,
            "t": self.t,
            "duration": self.duration,
            "shot_id": self.shot_id,
            "visual": self.visual,
            "big": self.big,
            "small": self.small,
            "sfx": self.sfx,
            "narration": self.narration,
            "energy": self.energy,
            "focus": self.focus,
            "params": self.params or {},
        }


def beats_from_shots(
    shots: list[dict[str, Any]],
    grid: list[float],
    *,
    energy_per_bar: list[float] | None = None,
) -> list[dict[str, Any]]:
    """把镜头按 ``beats`` 数铺到拍点网格上，逐拍展开为 beats.json。

    shot 字段：id, visual, big, small, sfx, narration, focus, params, beats。
    """
    out: list[dict[str, Any]] = []
    beat_index = 0
    for shot in shots:
        span = max(1, int(shot.get("beats") or 1))
        for _ in range(span):
            if beat_index >= len(grid):
                break
            t = grid[beat_index]
            nxt = grid[min(beat_index + 1, len(grid) - 1)]
            beat_in_bar = (beat_index % 4) + 1
            bar_index = beat_index // 4
            energy = 0.0
            if energy_per_bar and bar_index < len(energy_per_bar):
                energy = float(energy_per_bar[bar_index])
            out.append(
                Beat(
                    index=beat_index,
                    bar=bar_index + 1,
                    beat=beat_in_bar,
                    t=t,
                    duration=round(max(0.0, nxt - t), 4),
                    shot_id=str(shot.get("id") or f"shot{beat_index}"),
                    visual=str(shot.get("visual") or ""),
                    big=str(shot.get("big") or ""),
                    small=str(shot.get("small") or ""),
                    sfx=str(shot.get("sfx") or ""),
                    narration=str(shot.get("narration") or ""),
                    energy=energy,
                    focus=str(shot.get("focus") or ""),
                    params=dict(shot.get("params") or {}),
                ).to_dict()
            )
            beat_index += 1
        if beat_index >= len(grid):
            break
    return out


def build_beats(
    script: dict[str, Any],
    *,
    music_path: str | Path | None = None,
    duration_floor: float = 0.0,
) -> dict[str, Any]:
    """脚本 + 音乐 → beats.json。无音乐时用镜头 TTS 预估时长生成虚拟拍点。"""
    shots = list(script.get("shots") or [])
    if not shots:
        raise ValueError("script.shots is empty")
    if music_path:
        music = analyze_music(music_path)
        bpm = float(script.get("bpm") or music["bpm"])
        grid = build_grid(
            max(float(music["duration_s"]), float(duration_floor)),
            bpm=bpm,
            first_beat_s=float(music["first_beat_s"]),
        )
        source = "music"
        energy = music.get("energy_per_bar") or []
    else:
        # 虚拟拍点：每个镜头按其文字长度估时，再按 120 BPM 取整到拍。
        bpm = float(script.get("bpm") or 120.0)
        total = 0.0
        for shot in shots:
            text = str(shot.get("narration") or shot.get("big") or "")
            seconds = max(1.6, len(text) / 4.2)
            span = max(1, math.ceil(seconds / (60.0 / bpm)))
            shot["beats"] = max(int(shot.get("beats") or 0), span)
            total += shot["beats"] * (60.0 / bpm)
        grid = build_grid(total + 0.6, bpm=bpm, first_beat_s=0.0)
        source = "virtual"
        energy = []
    beats = beats_from_shots(shots, grid, energy_per_bar=energy)
    used_bars = max(1, math.ceil(len(beats) / 4))
    energy = list(energy)[:used_bars] if energy else []
    return {
        "schema": "hevi.warmgold.beats/1",
        "source": source,
        "bpm": bpm,
        "beat_s": round(60.0 / bpm, 4),
        "grid_len": len(grid),
        "total_s": round(sum(b["duration"] for b in beats), 4),
        "energy_per_bar": energy,
        "beats": beats,
    }


def load_beats(path: str | Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def save_beats(data: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
