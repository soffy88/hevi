"""Pure shot planning: camera-move filter expressions, xfade graphs, shot
lengths, transcript window picking, rule-based director shot lists."""

from __future__ import annotations

from typing import Any

MOVES = ("push", "pull", "pan_l", "pan_r")
DEFAULT_MOVES = ("push", "pan_r", "pull", "pan_l")


def camera_filter(*, move: str, d: float, width: int, height: int, fps: int = 30, grade: str = "") -> str:
    """ffmpeg -vf chain: fps, scale-cover, slow push/pull/pan via frame-evaluated crop."""
    if move not in MOVES:
        raise ValueError(f"unknown camera move {move!r}")
    if d <= 0:
        raise ValueError("shot duration must be positive")
    W, H = width, height
    if move in ("push", "pull"):
        k = f"(1+0.12*t/{d})" if move == "push" else f"(1.12-0.12*t/{d})"
        head = f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        crop = (
            f"scale=w='trunc({W}*{k}/2)*2':h='trunc({H}*{k}/2)*2':eval=frame,"
            f"crop={W}:{H}:x='(iw-{W})/2':y='(ih-{H})/2'"
        )
    else:
        sw, sh = int(W * 1.12) // 2 * 2, int(H * 1.12) // 2 * 2
        head = f"fps={fps},scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
        x = f"(iw-{W})*(1-t/{d})" if move == "pan_l" else f"(iw-{W})*t/{d}"
        crop = f"crop={W}:{H}:x='{x}':y='(ih-{H})/2'"
    return f"{head}{crop},setsar=1{(',' + grade) if grade else ''},format=yuv420p"


def source_offset(*, source_dur: float, d: float, ss: float | None = None) -> float:
    """Start inside the source: a third of the slack by default, clamped in range."""
    if ss is None:
        ss = max(0.0, (source_dur - d) / 3)
    return max(0.0, min(ss, max(0.0, source_dur - d - 0.05)))


def xfade_graph(*, durations: list[float], xd: float, transition: str = "fade") -> tuple[str, str]:
    """filter_complex for chained xfades over inputs 0..n-1 -> (graph, output label)."""
    if len(durations) < 2:
        raise ValueError("xfade needs at least two shots")
    if any(d <= xd for d in durations):
        raise ValueError("every shot must be longer than the crossfade")
    fc, prev, off = [], "[0:v]", 0.0
    for i in range(1, len(durations)):
        off += durations[i - 1] - xd
        lab = f"[x{i}]"
        fc.append(f"{prev}[{i}:v]xfade=transition={transition}:duration={xd}:offset={off:.3f}{lab}")
        prev = lab
    return ";".join(fc), prev


def narration_shot_lengths(
    cues: list[tuple[float, float, str]], *, xd: float, pad: float = 0.35, tail: float = 1.2
) -> list[float]:
    """Shot i covers narration line i (+gap); later shots absorb the crossfade overlap."""
    n = len(cues)
    return [(b - a) + pad + (xd if i else 0.0) + (tail if i == n - 1 else 0.0) for i, (a, b, _) in enumerate(cues)]


def pick_windows(segs: list[dict[str, Any]], *, n: int = 2, target: tuple[float, float] = (18, 32)) -> list[tuple[int, int]]:
    """Greedy non-overlapping windows of whole transcript segments whose span is in ``target``."""
    wins: list[tuple[int, int]] = []
    i = 0
    while i < len(segs) and len(wins) < n:
        j = i
        while j < len(segs) and segs[j]["end"] - segs[i]["start"] < target[0]:
            j += 1
        if j >= len(segs):
            break
        if segs[j]["end"] - segs[i]["start"] <= target[1]:
            wins.append((i, j))
            i = j + 1
        else:
            i += 1
    return wins


_SIZES = ("WIDE", "MEDIUM", "CLOSE", "MEDIUM", "WIDE")
_SIZE_MOVE = {"WIDE": ("pull", "pan_l"), "MEDIUM": ("push", "pan_r"), "CLOSE": ("push",)}


def director_shot_list(
    *, texts: list[str], queries: list[str], overrides: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Rule-based director: open WIDE, tighten to CLOSE mid-piece, release WIDE at
    the end; camera follows shot size.  ``overrides`` (per shot) win when given."""
    n = len(texts)
    out = []
    for i, (text, query) in enumerate(zip(texts, queries, strict=False)):
        if n == 1:
            size = "WIDE"
        elif i == 0 or i == n - 1:
            size = "WIDE"
        else:
            size = _SIZES[1 + (i - 1) % 3]
        moves = _SIZE_MOVE[size]
        shot = {"shot": i + 1, "size": size, "camera": moves[i % len(moves)], "query": query, "narration": text}
        if overrides and i < len(overrides):
            o = overrides[i] or {}
            for key in ("size", "camera", "query"):
                if o.get(key):
                    shot[key] = str(o[key])
        if shot["camera"] not in MOVES:
            raise ValueError(f"shot {i + 1}: unknown camera {shot['camera']!r}")
        out.append(shot)
    return out


#: caveman routine action beats (seconds) used to time character_animation lines
CAVEMAN_BEATS = (0.6, 4.8, 7.8, 10.1)
CAVEMAN_SECONDS = 12.0


def place_on_beats(durations: list[float], *, beats: tuple[float, ...] = CAVEMAN_BEATS, total: float = CAVEMAN_SECONDS) -> list[float]:
    """Start time for each line on its action beat; refuse lines that would overlap
    the next beat or run past the scene."""
    if len(durations) > len(beats):
        raise ValueError(f"at most {len(beats)} lines fit the action beats")
    starts = list(beats[: len(durations)])
    for i, (s, d) in enumerate(zip(starts, durations, strict=True)):
        limit = beats[i + 1] if i + 1 < len(beats) else total
        if s + d > limit + 0.6:
            raise ValueError(f"line {i + 1} lasts {d:.2f}s and overruns its beat window ({limit - s:.2f}s)")
    return starts


__all__ = [
    "CAVEMAN_BEATS",
    "CAVEMAN_SECONDS",
    "DEFAULT_MOVES",
    "MOVES",
    "camera_filter",
    "director_shot_list",
    "narration_shot_lengths",
    "pick_windows",
    "place_on_beats",
    "source_offset",
    "xfade_graph",
]
