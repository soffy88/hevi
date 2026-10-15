"""BPM Grid snapping and timing utilities for Motion FX.

Supports musical meter grid alignment (quarter notes, 8th notes, 16th notes, etc.)
allowing transitions, cuts, and visual events to snap strictly to rhythmic beats.
"""

from __future__ import annotations

import math
from typing import Union


def parse_division(division: Union[int, float, str]) -> float:
    """Parse a musical division representation into a numeric value.

    Standard musical subdivisions:
      - 1 or "1/1": Whole note (4 beats in 4/4)
      - 2 or "1/2": Half note (2 beats)
      - 4 or "1/4": Quarter note (1 beat)
      - 8 or "1/8": Eighth note (0.5 beats)
      - 16 or "1/16": Sixteenth note (0.25 beats)
      - 32 or "1/32": Thirty-second note (0.125 beats)
    """
    if isinstance(division, str):
        division_str = division.strip()
        if "/" in division_str:
            parts = division_str.split("/")
            if len(parts) == 2:
                num = float(parts[0])
                denom = float(parts[1])
                if num <= 0 or denom <= 0:
                    raise ValueError(f"Invalid division fraction: {division}")
                # "1/4" means denominator 4
                return denom / num
        return float(division_str)

    val = float(division)
    if val <= 0:
        raise ValueError(f"Division must be positive, got {division}")
    return val


def get_grid_step(bpm: float = 120.0, division: Union[int, float, str] = 4) -> float:
    """Calculate the duration in seconds of a single grid step.

    In 4/4 time signature:
      Whole note (div=1) = 4 * 60 / bpm
      Quarter note (div=4, 1 beat) = 60 / bpm
      Eighth note (div=8, 0.5 beat) = 30 / bpm
      Sixteenth note (div=16, 0.25 beat) = 15 / bpm

    Step formula: 240.0 / (bpm * division)
    """
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")
    div_val = parse_division(division)
    return 240.0 / (bpm * div_val)


def snap_to_grid(
    t: float,
    bpm: float = 120.0,
    division: Union[int, float, str] = 4,
    min_time: float = 0.0,
) -> float:
    """Snap timestamp `t` to the nearest BPM grid line.

    Args:
        t: Time in seconds to snap.
        bpm: Beats per minute (default 120.0).
        division: Musical division (e.g. 4 for quarter note/1 beat, 8 for 1/8 note).
        min_time: Minimum clamped time (default 0.0).

    Returns:
        Snapped timestamp in seconds rounded to 6 decimal places.
    """
    step = get_grid_step(bpm, division)
    if step <= 0:
        return max(min_time, t)

    idx = round(t / step)
    snapped = idx * step
    if snapped < min_time:
        snapped = min_time
    return round(snapped, 6)


def generate_beat_grid(
    duration: float,
    bpm: float = 120.0,
    division: Union[int, float, str] = 4,
    start_time: float = 0.0,
) -> list[float]:
    """Generate all grid timestamps up to `duration`."""
    step = get_grid_step(bpm, division)
    times: list[float] = []
    t = start_time
    while t <= duration + 1e-7:
        times.append(round(t, 6))
        t += step
    return times
