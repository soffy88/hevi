"""Launch-film rhythm sheets: data model, validation and measurement.

A *rhythm sheet* (节奏单) is the time-axis plan for a product launch film:
an ordered list of stretches that cover the whole duration, each declaring
its role, planned energy, event density, contrast changes versus the
previous stretch and music note.  The human-readable rules live in
``docs/rules/launch_rhythm.md``; this module is the machine side of the
same card — :func:`validate_sheet` checks a sheet against the card's hard
rules and :func:`measure_rhythm` compares a finished (or rough) cut
against the plan.

Measurement is deliberately dependency-light: ffmpeg decodes audio to
mono f32le at 16 kHz and video to 96x54 grayscale raw frames sampled at
10 fps; numpy does the arithmetic.  No new dependencies, no network, no
model downloads.

Rule provenance: the thresholds are distilled from huashu-motion's
``rhythm.md`` field measurements (21 real launch films measured, 142
high-engagement films dissected; MIT License) and re-worded / adapted
to hevi's lines in ``docs/rules/launch_rhythm.md``.
"""

from __future__ import annotations

import itertools
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

ROUTES = ("continuous", "montage", "hybrid")
ROLES = ("hook", "build", "stop", "peak", "resolve", "section")
#: Contrast dimensions a stretch may declare it changes vs the previous one.
CONTRAST_DIMENSIONS = (
    "shot_scale", "speed", "easing_family", "camera",
    "density", "colour", "music_texture",
)

_COVER_TOL_S = 0.02  # coverage tolerance for float-authored sheets
HOOK_FIRST_EVENT_MAX_S = 3.0
BURST_WINDOW = (0.30, 0.60)  # fraction of duration where the burst must sit
BURST_MIN_EVENTS_PER_BAR = 4.0
STOP_MIN_S, STOP_MAX_S = 0.5, 1.6
#: A stretch whose sampled frame-to-frame motion is below this (mean
#: absolute luma difference, 0-255 scale) counts as visually dead.
DEAD_MOTION_THRESHOLD = 1.0
_AUDIO_SR = 16000
_VIDEO_FPS = 10
_VIDEO_W, _VIDEO_H = 96, 54


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Stretch:
    name: str
    start_s: float
    end_s: float
    role: str  # hook | build | stop | peak | resolve | section
    energy: float  # planned energy, 0-10
    events_per_bar: float
    changes: list[str] = field(default_factory=list)
    music: str = ""
    hero: bool = False
    #: Absolute time (s) of the first event inside this stretch.  Only
    #: meaningful on the hook stretch; ``None`` means "at start_s".
    first_event_s: float | None = None

    @property
    def duration_s(self) -> float:
        return float(self.end_s) - float(self.start_s)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "start_s": float(self.start_s),
            "end_s": float(self.end_s),
            "role": self.role,
            "energy": float(self.energy),
            "events_per_bar": float(self.events_per_bar),
            "changes": list(self.changes),
            "music": self.music,
            "hero": bool(self.hero),
        }
        if self.first_event_s is not None:
            out["first_event_s"] = float(self.first_event_s)
        return out

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Stretch:
        return cls(
            name=str(d.get("name", "")),
            start_s=float(d.get("start_s", 0.0)),
            end_s=float(d.get("end_s", 0.0)),
            role=str(d.get("role", "")),
            energy=float(d.get("energy", 0.0)),
            events_per_bar=float(d.get("events_per_bar", 0.0)),
            changes=[str(c) for c in d.get("changes") or []],
            music=str(d.get("music") or ""),
            hero=bool(d.get("hero", False)),
            first_event_s=(
                float(d["first_event_s"]) if d.get("first_event_s") is not None else None
            ),
        )


@dataclass
class RhythmSheet:
    title: str
    route: str  # continuous | montage | hybrid
    bpm: float
    duration_s: float
    stretches: list[Stretch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "route": self.route,
            "bpm": float(self.bpm),
            "duration_s": float(self.duration_s),
            "stretches": [s.to_dict() for s in self.stretches],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RhythmSheet:
        return cls(
            title=str(d.get("title", "")),
            route=str(d.get("route", "")),
            bpm=float(d.get("bpm", 0.0)),
            duration_s=float(d.get("duration_s", 0.0)),
            stretches=[Stretch.from_dict(s) for s in d.get("stretches") or []],
        )


def coerce_sheet(sheet: RhythmSheet | dict[str, Any]) -> RhythmSheet:
    if isinstance(sheet, RhythmSheet):
        return sheet
    if isinstance(sheet, dict):
        return RhythmSheet.from_dict(sheet)
    raise CapabilityError(
        f"rhythm_sheet: sheet must be a RhythmSheet or dict, got {type(sheet).__name__}"
    )


def bar_duration_s(bpm: float) -> float:
    """One bar (4 beats) in seconds at ``bpm``."""
    return 240.0 / float(bpm)


# ---------------------------------------------------------------------------
# Validation (hard rules from docs/rules/launch_rhythm.md)
# ---------------------------------------------------------------------------

def _issue(rule: str, message: str, stretch: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"rule": rule, "message": message}
    if stretch is not None:
        out["stretch"] = stretch
    return out


def validate_sheet(sheet: RhythmSheet | dict[str, Any]) -> dict[str, Any]:
    """Validate a rhythm sheet.  Returns ``{ok, violations, warnings}``.

    ``violations`` / ``warnings`` are lists of
    ``{rule, message, stretch?}`` dicts.  Judgement calls, spelled out:

    * Coverage is checked in declared order with a 0.02 s tolerance:
      first stretch must start at 0, each next start must equal the
      previous end, the last end must equal ``duration_s``.
    * Hook: the *first* stretch must have ``role == "hook"`` and its
      first event must land at or before 3.0 s.  The first-event time
      is the stretch's ``first_event_s`` when declared, otherwise its
      ``start_s`` (so a plain hook starting at 0 passes by default; a
      hook declaring ``first_event_s: 4`` fails).
    * Burst: some stretch must reach ``events_per_bar >= 4``.  None
      anywhere -> violation.  One exists but no >=4 stretch overlaps
      the 30%-60% window -> warning (position off, not missing).
    * Hero: exactly one stretch with ``hero=True``; its energy must be
      the sheet maximum and it must come after the burst stretch
      (a later stretch in the list, starting no earlier than the burst
      starts).  Violations otherwise.
    * Stop: a ``role == "stop"`` stretch outside 0.5-1.6 s is a
      warning; a stop not immediately followed by a peak stretch or
      the hero stretch is a violation.
    * Contrast: every non-first stretch declares, in ``changes``, the
      dimensions it changes versus the previous stretch.  Fewer than
      2 -> violation.  Peak / hero stretches with 2-3 -> warning
      (the drop should change (nearly) everything; >=4 is the bar).
    * Dead stretches: a non-stop stretch with ``events_per_bar == 0``,
      or longer than two bars (at the sheet BPM) with
      ``events_per_bar < 1``, is a violation.  Planned stops are exempt.
    """
    sh = coerce_sheet(sheet)
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    stretches = sh.stretches

    if sh.route not in ROUTES:
        violations.append(_issue(
            "invalid_route", f"route must be one of {ROUTES}, got {sh.route!r}"))
    if not (sh.bpm and sh.bpm > 0):
        violations.append(_issue("invalid_bpm", f"bpm must be > 0, got {sh.bpm!r}"))
    if not (sh.duration_s and sh.duration_s > 0):
        violations.append(_issue(
            "invalid_duration", f"duration_s must be > 0, got {sh.duration_s!r}"))
    if not stretches:
        violations.append(_issue("no_stretches", "sheet declares no stretches"))
        return {"ok": False, "violations": violations, "warnings": warnings}

    for s in stretches:
        if s.role not in ROLES:
            violations.append(_issue(
                "invalid_role", f"role must be one of {ROLES}, got {s.role!r}", s.name))
        if not (0.0 <= float(s.energy) <= 10.0):
            violations.append(_issue(
                "energy_out_of_range", f"energy must be 0-10, got {s.energy}", s.name))
        if s.end_s <= s.start_s:
            violations.append(_issue(
                "non_positive_stretch",
                f"stretch ends at/before it starts ({s.start_s}..{s.end_s})", s.name))

    # -- coverage: 0 -> duration_s, no gaps, no overlaps -------------------
    if abs(stretches[0].start_s - 0.0) > _COVER_TOL_S:
        violations.append(_issue(
            "coverage_start",
            f"first stretch starts at {stretches[0].start_s}s, not 0", stretches[0].name))
    for prev, cur in itertools.pairwise(stretches):
        delta = float(cur.start_s) - float(prev.end_s)
        if delta > _COVER_TOL_S:
            violations.append(_issue(
                "coverage_gap",
                f"gap of {delta:.3f}s between {prev.name!r} and {cur.name!r}", cur.name))
        elif delta < -_COVER_TOL_S:
            violations.append(_issue(
                "coverage_overlap",
                f"overlap of {-delta:.3f}s between {prev.name!r} and {cur.name!r}",
                cur.name))
    if abs(stretches[-1].end_s - float(sh.duration_s)) > _COVER_TOL_S:
        violations.append(_issue(
            "coverage_end",
            f"last stretch ends at {stretches[-1].end_s}s, "
            f"sheet duration is {sh.duration_s}s", stretches[-1].name))

    # -- hook ---------------------------------------------------------------
    first = stretches[0]
    if first.role != "hook":
        violations.append(_issue(
            "hook_missing",
            f"first stretch role is {first.role!r}, not 'hook'", first.name))
    else:
        first_event = (
            float(first.first_event_s) if first.first_event_s is not None
            else float(first.start_s)
        )
        if first_event > HOOK_FIRST_EVENT_MAX_S:
            violations.append(_issue(
                "hook_first_event_late",
                f"hook's first event is at {first_event}s, must be "
                f"<= {HOOK_FIRST_EVENT_MAX_S}s", first.name))

    # -- burst --------------------------------------------------------------
    burst_idx = [i for i, s in enumerate(stretches)
                 if float(s.events_per_bar) >= BURST_MIN_EVENTS_PER_BAR]
    burst_stretch: Stretch | None = None
    if not burst_idx:
        violations.append(_issue(
            "burst_missing",
            f"no stretch reaches events_per_bar >= {BURST_MIN_EVENTS_PER_BAR:g} "
            "(the mid-film burst is missing)"))
    else:
        win_lo = BURST_WINDOW[0] * float(sh.duration_s)
        win_hi = BURST_WINDOW[1] * float(sh.duration_s)
        in_window = [i for i in burst_idx
                     if stretches[i].start_s < win_hi and stretches[i].end_s > win_lo]
        if not in_window:
            warnings.append(_issue(
                "burst_position",
                f"burst stretch(es) sit outside the "
                f"{BURST_WINDOW[0]:.0%}-{BURST_WINDOW[1]:.0%} window "
                f"({win_lo:.1f}-{win_hi:.1f}s)",
                stretches[burst_idx[0]].name))
            burst_stretch = stretches[burst_idx[0]]
        else:
            burst_stretch = stretches[in_window[0]]

    # -- hero ---------------------------------------------------------------
    heroes = [(i, s) for i, s in enumerate(stretches) if s.hero]
    if len(heroes) != 1:
        violations.append(_issue(
            "hero_count", f"exactly one hero stretch is required, found {len(heroes)}"))
    else:
        hero_idx, hero = heroes[0]
        max_energy = max(float(s.energy) for s in stretches)
        if float(hero.energy) < max_energy:
            violations.append(_issue(
                "hero_not_max_energy",
                f"hero energy {hero.energy} is not the sheet maximum {max_energy}",
                hero.name))
        if burst_stretch is not None:
            burst_pos = stretches.index(burst_stretch)
            if hero_idx <= burst_pos or float(hero.start_s) < float(burst_stretch.start_s):
                violations.append(_issue(
                    "hero_order",
                    f"hero {hero.name!r} must come after the burst "
                    f"stretch {burst_stretch.name!r}", hero.name))

    # -- stops --------------------------------------------------------------
    for i, s in enumerate(stretches):
        if s.role != "stop":
            continue
        if not (STOP_MIN_S <= s.duration_s <= STOP_MAX_S):
            warnings.append(_issue(
                "stop_duration",
                f"stop lasts {s.duration_s:.2f}s, outside "
                f"{STOP_MIN_S}-{STOP_MAX_S}s", s.name))
        nxt = stretches[i + 1] if i + 1 < len(stretches) else None
        if nxt is None or not (nxt.role == "peak" or nxt.hero):
            violations.append(_issue(
                "stop_not_followed_by_peak",
                "a stop must be immediately followed by a peak or the hero stretch",
                s.name))

    # -- contrast -----------------------------------------------------------
    for i, s in enumerate(stretches):
        if i == 0:
            continue
        n_changes = len(s.changes or [])
        if n_changes < 2:
            violations.append(_issue(
                "contrast_too_few",
                f"stretch changes only {n_changes} dimension(s) vs the previous "
                "stretch; at least 2 must change at every boundary", s.name))
        elif (s.role == "peak" or s.hero) and n_changes < 4:
            warnings.append(_issue(
                "contrast_peak_thin",
                f"peak/hero stretch changes only {n_changes} dimension(s); "
                "the drop should change at least 4", s.name))

    # -- dead stretches -----------------------------------------------------
    two_bars = bar_duration_s(sh.bpm) * 2 if sh.bpm and sh.bpm > 0 else None
    for s in stretches:
        if s.role == "stop":
            continue
        if float(s.events_per_bar) == 0:
            violations.append(_issue(
                "dead_stretch",
                "non-stop stretch declares events_per_bar == 0", s.name))
        elif (two_bars is not None and s.duration_s > two_bars
              and float(s.events_per_bar) < 1):
            violations.append(_issue(
                "dead_stretch",
                f"stretch runs {s.duration_s:.1f}s (> 2 bars = {two_bars:.1f}s) "
                f"with events_per_bar {s.events_per_bar} < 1", s.name))

    return {"ok": not violations, "violations": violations, "warnings": warnings}


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

def _ffmpeg_bin() -> str:
    try:
        from hevi.renderers.ffmpeg import resolve_ffmpeg_bin
        return resolve_ffmpeg_bin()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def _decode_audio(media: Path) -> Any:
    import numpy as np
    cmd = [_ffmpeg_bin(), "-v", "error", "-i", str(media),
           "-vn", "-ac", "1", "-ar", str(_AUDIO_SR), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise CapabilityError(
            f"motion.rhythm_sheet: ffmpeg could not decode audio of {media}: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _decode_frames(media: Path) -> Any:
    import numpy as np
    vf = f"fps={_VIDEO_FPS},scale={_VIDEO_W}:{_VIDEO_H},format=gray"
    cmd = [_ffmpeg_bin(), "-v", "error", "-i", str(media),
           "-an", "-vf", vf, "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise CapabilityError(
            f"motion.rhythm_sheet: ffmpeg could not decode video of {media}: "
            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    frame_bytes = _VIDEO_W * _VIDEO_H
    n_frames = len(proc.stdout) // frame_bytes
    if n_frames == 0:
        raise CapabilityError(
            f"motion.rhythm_sheet: no video frames decoded from {media}")
    return np.frombuffer(
        proc.stdout[: n_frames * frame_bytes], dtype=np.uint8
    ).reshape(n_frames, frame_bytes).astype(np.float32)


def _minmax(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def measure_rhythm(media_path: str | Path,
                   sheet: RhythmSheet | dict[str, Any]) -> dict[str, Any]:
    """Measure a cut against its rhythm sheet, per stretch.

    Per stretch: audio RMS in dB (mono 16 kHz decode), visual motion
    (mean absolute difference of consecutive 96x54 grayscale frames
    sampled at 10 fps, averaged inside the stretch), planned energy
    normalised to 0-1, measured audio energy normalised to 0-1 across
    stretches, their signed difference, and a ``dead_flag`` when the
    measured motion is below :data:`DEAD_MOTION_THRESHOLD` and the
    stretch is not a planned stop.  The report also carries the Pearson
    correlation between the planned and measured energy shapes.

    Raises :class:`CapabilityError` when the media cannot be read.
    """
    import numpy as np
    sh = coerce_sheet(sheet)
    media = Path(media_path)
    if not media.is_file():
        raise CapabilityError(f"motion.rhythm_sheet: media file not found: {media}")

    audio = _decode_audio(media)
    frames = _decode_frames(media)

    rows: list[dict[str, Any]] = []
    for s in sh.stretches:
        a0, a1 = int(s.start_s * _AUDIO_SR), int(s.end_s * _AUDIO_SR)
        chunk = audio[a0:a1] if a1 > a0 else audio[0:0]
        if chunk.size:
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            rms_db = 20.0 * math.log10(rms) if rms > 0 else -120.0
        else:
            rms_db = -120.0
        f0 = max(0, int(s.start_s * _VIDEO_FPS))
        f1 = min(frames.shape[0], math.ceil(s.end_s * _VIDEO_FPS))
        motion = (
            float(np.mean(np.abs(np.diff(frames[f0:f1], axis=0))))
            if f1 - f0 >= 2 else 0.0
        )
        rows.append({
            "name": s.name, "start_s": float(s.start_s), "end_s": float(s.end_s),
            "role": s.role, "hero": bool(s.hero),
            "planned_energy": float(s.energy),
            "audio_rms_db": round(rms_db, 3),
            "motion": round(motion, 4),
            "dead_flag": bool(motion < DEAD_MOTION_THRESHOLD and s.role != "stop"),
        })

    planned_norm = _minmax([r["planned_energy"] for r in rows]) if rows else []
    audio_norm = _minmax([r["audio_rms_db"] for r in rows]) if rows else []
    for row, p_norm, a_norm in zip(rows, planned_norm, audio_norm, strict=True):
        row["planned_energy_norm"] = round(p_norm, 4)
        row["audio_energy_norm"] = round(a_norm, 4)
        row["energy_diff"] = round(p_norm - a_norm, 4)

    correlation: float | None = None
    if len(rows) >= 2:
        p = np.asarray(planned_norm, dtype=np.float64)
        a = np.asarray(audio_norm, dtype=np.float64)
        if float(np.std(p)) > 1e-9 and float(np.std(a)) > 1e-9:
            correlation = round(float(np.corrcoef(p, a)[0, 1]), 4)

    return {
        "media_path": str(media),
        "motion_threshold": DEAD_MOTION_THRESHOLD,
        "audio_sample_rate": _AUDIO_SR,
        "video_sample_fps": _VIDEO_FPS,
        "stretches": rows,
        "shape_correlation": correlation,
        "dead_stretches": [r["name"] for r in rows if r["dead_flag"]],
    }


__all__ = [
    "CONTRAST_DIMENSIONS", "DEAD_MOTION_THRESHOLD", "ROLES", "ROUTES",
    "RhythmSheet", "Stretch", "bar_duration_s", "coerce_sheet",
    "measure_rhythm", "validate_sheet",
]
