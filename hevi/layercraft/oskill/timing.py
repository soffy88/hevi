"""oskill: easing + beat-staggered layer timing (pure functions)."""

from __future__ import annotations

import math


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float, s: float = 1.70158) -> float:
    t = clamp01(t) - 1
    return 1 + (s + 1) * t**3 + s * t**2


def local(t: float, start: float, dur: float) -> float:
    """Normalised 0..1 progress of a clip starting at ``start``."""
    return clamp01((t - start) / dur) if dur > 0 else float(t >= start)


def stagger_starts(n: int, *, bpm: float = 120.0, step_beats: float = 0.5, offset: float = 0.0) -> list[float]:
    """Start time of each of ``n`` layers, each delayed ``step_beats`` (default half a beat)."""
    if n < 0 or bpm <= 0:
        raise ValueError("n must be >=0 and bpm > 0")
    step = 60.0 / bpm * step_beats
    return [offset + i * step for i in range(n)]


def layer_enter_state(t: float, start: float, *, dur: float = 0.6, rise: float = 40.0,
                      stroke_dur: float | None = None) -> dict:
    """Fade + slide-up + stroke draw-on state of one layer at time ``t``.

    Returns alpha (0..1), dy (px, positive = still below rest), stroke (0..1 draw progress).
    """
    p = local(t, start, dur)
    e = ease_out_cubic(p)
    sp = ease_in_out_cubic(local(t, start, stroke_dur if stroke_dur is not None else dur * 1.4))
    return {"alpha": e, "dy": rise * (1 - e), "stroke": sp, "progress": p}


def boil_seed(frame: int, base_seed: int = 0, hold: int = 3) -> int:
    """Boiling-line seed: a new seed every ``hold`` frames (2s/3s 'on twos/threes')."""
    if hold < 1:
        raise ValueError("hold must be >= 1")
    return int(base_seed) + int(frame) // int(hold)


def sway(t: float, amp: float, period: float, phase: float = 0.0) -> float:
    return amp * math.sin(2 * math.pi * t / period + phase)
