"""G0.2 ffmpeg silencedetect 能力探测(A8 前置)。

用已知静音片段验证本机 ffmpeg 能否分辨本项目最短声明静音(320ms)。
失败/版本不支持小数时长 -> 调用方记 SILENCE_PROBE_FAILED,相关检查
NOT_EVALUABLE,不得 PASS。ffmpeg 版本随结果 pin,写入 receipt。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from hevi.verdict.delivery_gate import parse_silence_events


@dataclass(frozen=True)
class SilenceProbeResult:
    ffmpeg_version: str
    silence_ms: int
    detected: bool
    events: tuple[tuple[float, float], ...] = field(default_factory=tuple)
    detail: str = ""


class SilenceProbeFailed(RuntimeError):
    """SILENCE_PROBE_FAILED:探测失败,静音检查一律 NOT_EVALUABLE。"""


def ffmpeg_version() -> str:
    try:
        proc = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=30)
    except OSError as exc:
        raise SilenceProbeFailed(f"ffmpeg not runnable: {exc}") from exc
    first = proc.stdout.splitlines()[0] if proc.stdout else ""
    if not first:
        raise SilenceProbeFailed("ffmpeg -version produced no output")
    return first.strip()


def make_tone_silence_tone(path: Path, *, tone_s: float = 1.0, silence_ms: int = 320) -> Path:
    """合成 已知静音片段:tone + 数字静音 + tone。构造即真值,无需标注。"""
    silence_s = silence_ms / 1000
    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_s}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono:d={silence_s}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_s}",
        "-filter_complex", "[0:a][1:a][2:a]concat=n=3:v=0:a=1[a]",
        "-map", "[a]", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not path.exists() or path.stat().st_size == 0:
        raise SilenceProbeFailed(f"synthetic silence fixture failed: {proc.stderr[-300:]}")
    return path


def probe_silence_resolution(
    workdir: Path, *, silence_ms: int = 320, noise_db: int = -60, tol_ms: int = 80
) -> SilenceProbeResult:
    """探测能否分辨 silence_ms 的静音。返回结果,不抛(调用方按 detected 裁决)。"""
    version = ffmpeg_version()
    fixture = make_tone_silence_tone(workdir / f"silence_{silence_ms}ms.wav", silence_ms=silence_ms)
    floor_s = silence_ms / 1000
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(fixture),
         "-af", f"silencedetect=noise={noise_db}dB:d={floor_s}",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    events = tuple(parse_silence_events(proc.stderr, floor_s=floor_s))
    ok = (
        len(events) == 1
        and abs(events[0][0] - 1.0) * 1000 <= tol_ms
        and abs(events[0][1] - floor_s) * 1000 <= tol_ms
    )
    detail = f"events={events}" if not ok else ""
    return SilenceProbeResult(version, silence_ms, ok, events, detail)
