"""Measured delivery gates (port of talkcraft freeze_probe / motion_check /
sfx_check / contact_sheet).  Every gate records the measured number next to
its threshold; nothing is a bare boolean claim."""

from __future__ import annotations

import re
from pathlib import Path
from statistics import mean
from typing import Any

from hevi.layer4_legacy.talkcraft.oprim_impl.sync import GateMeasure, SentenceTiming
from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, probe, run

_FREEZE_START = re.compile(r"freeze_start: ([\d.]+)")
_FREEZE_END = re.compile(r"freeze_end: ([\d.]+)")
_BLACK = re.compile(r"black_duration:([\d.]+)")
_YDIF = re.compile(r"lavfi\.signalstats\.YDIF=([\d.]+)")
_LUFS = re.compile(r"I:\s+(-?[\d.]+) LUFS")
_SIL_DUR = re.compile(r"silence_duration: ([\d.]+)")


def freeze_spans(*, path: Path, total_s: float, noise: float = 0.001, min_s: float = 1.0) -> list[tuple[float, float]]:
    log = run([FFMPEG, "-v", "info", "-i", str(path), "-vf", f"freezedetect=n={noise}:d={min_s}", "-an", "-f", "null", "-"])
    starts = [float(x) for x in _FREEZE_START.findall(log)]
    ends = [float(x) for x in _FREEZE_END.findall(log)]
    if len(ends) < len(starts):
        ends.append(total_s)
    return list(zip(starts, ends, strict=False))


def mean_ydif(*, path: Path) -> float:
    log = run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf", "fps=10,scale=480:-2,signalstats,metadata=print:key=lavfi.signalstats.YDIF:file=-", "-an", "-f", "null", "-"]
    )
    vals = [float(v) for v in _YDIF.findall(log)]
    return mean(vals[1:]) if len(vals) > 1 else 0.0


def black_seconds(*, path: Path) -> float:
    log = run([FFMPEG, "-v", "info", "-i", str(path), "-vf", "blackdetect=d=0.3:pix_th=0.08", "-an", "-f", "null", "-"])
    return sum(float(x) for x in _BLACK.findall(log))


def loudness(*, path: Path) -> tuple[float, float]:
    """(integrated LUFS, longest silence s at -45 dB)."""
    log = run([FFMPEG, "-v", "info", "-i", str(path), "-af", "ebur128,silencedetect=n=-45dB:d=0.8", "-vn", "-f", "null", "-"])
    lufs = _LUFS.findall(log)
    sil = [float(x) for x in _SIL_DUR.findall(log)]
    return (float(lufs[-1]) if lufs else -99.0, max(sil) if sil else 0.0)


def contact_sheet(*, path: Path, out: Path, total_s: float, cols: int = 4, rows: int = 3) -> Path:
    n = cols * rows
    rate = max(0.05, n / max(total_s, 1.0))
    run([FFMPEG, "-y", "-v", "error", "-i", str(path), "-vf", f"fps={rate:.4f},scale=480:-2,tile={cols}x{rows}:padding=4", "-frames:v", "1", str(out)])
    return out


def measure(
    *,
    path: Path,
    expected_s: float,
    timings: list[SentenceTiming],
    cards: list[str],
    expect_w: int,
    expect_h: int,
) -> tuple[list[GateMeasure], dict[str, Any]]:
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    dur = float(info["format"]["duration"])
    num, den = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = num / den if den else 0.0
    spans = freeze_spans(path=path, total_s=dur)
    longest = max((e - s for s, e in spans), default=0.0)
    frozen = sum(e - s for s, e in spans)
    ydif = mean_ydif(path=path)
    black = black_seconds(path=path)
    lufs, longest_sil = loudness(path=path) if has_audio else (-99.0, dur)
    ratios = [t.match_ratio for t in timings] or [0.0]
    g = [
        GateMeasure("resolution", float(v["width"] * v["height"]), f"=={expect_w}x{expect_h}", v["width"] == expect_w and v["height"] == expect_h, f"{v['width']}x{v['height']}"),
        GateMeasure("duration_delta_s", round(abs(dur - expected_s), 3), "<=0.5", abs(dur - expected_s) <= 0.5, f"{dur:.2f}s vs {expected_s:.2f}s"),
        GateMeasure("longest_freeze_s", round(longest, 2), "<=2.5", longest <= 2.5),
        GateMeasure("frozen_share", round(frozen / dur, 3) if dur else 1.0, "<=0.20", dur > 0 and frozen / dur <= 0.20),
        GateMeasure("mean_ydif", round(ydif, 3), ">=0.25", ydif >= 0.25, "mean luma frame diff @10fps"),
        GateMeasure("black_s", round(black, 2), "<=0.5", black <= 0.5),
        GateMeasure("integrated_lufs", round(lufs, 1), "-18..-12", -18.0 <= lufs <= -12.0),
        GateMeasure("longest_silence_s", round(longest_sil, 2), "<=1.5", longest_sil <= 1.5),
        GateMeasure("align_min_match", round(min(ratios), 3), ">=0.5", min(ratios) >= 0.5),
        GateMeasure("align_mean_match", round(mean(ratios), 3), ">=0.8", mean(ratios) >= 0.8),
        GateMeasure("distinct_cards", float(len(set(cards))), f">={min(6, len(cards))}", len(set(cards)) >= min(6, len(cards))),
    ]
    facts = {"width": v["width"], "height": v["height"], "duration_s": dur, "fps": fps, "has_audio": has_audio, "freeze_spans": spans}
    return g, facts
