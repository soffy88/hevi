"""Timestamp-driven route progress for the map-route line.

Two modes:

* **Alignment-driven (preferred).**  Input is a hevi word-level alignment
  artefact — the exact shape written by ``hevi.audio.whisper_alignment``
  (and the ElevenLabs forced-alignment provider; see
  ``output/storyfilm/*/alignment.json``)::

      {"alignment_source": "whisper_asr_local", "is_estimated": false,
       "duration_ms": 44039,
       "words": [{"text": "小", "start_ms": 140, "end_ms": 200}, ...]}

  Variants with ``word`` instead of ``text`` and second-based
  ``start``/``end`` fields are also accepted.  Each stop's ``narration``
  segment is located sequentially in the alignment's character stream; the
  segment's last word end-time becomes the moment the drawn route reaches
  that stop.  Stops whose narration cannot be located fall back to their
  proportional share and are flagged in the returned report.

* **Dwell-driven (no alignment).**  Each stop's ``dwell_s`` is the time
  budget for travelling to it plus holding on it (the first stop's dwell
  is the opening hold).  Route progress is spread evenly across legs.

Either way the output is a milestone list ``[(t_s, fraction), ...]`` plus
the total duration; :func:`fraction_at` interpolates linearly, and the
Chromium renderer receives the same milestones so Python and the drawn
frames can never disagree about progress.
"""

from __future__ import annotations

from typing import Any

from .errors import MapRouteError

_PUNCT = set("，。！？；：、,.!?;:·…—-「」『』（）()《》<>\"'“”‘’ \t\r\n")


def _norm(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PUNCT)


def parse_alignment(data: Any) -> list[dict[str, Any]]:
    """Normalise an alignment artefact to [{text, start_s, end_s}, ...]."""
    if isinstance(data, dict):
        words = data.get("words")
        if words is None and isinstance(data.get("alignment"), dict):
            words = data["alignment"].get("words")
    elif isinstance(data, list):
        words = data
    else:
        words = None
    if not isinstance(words, list) or not words:
        raise MapRouteError("alignment has no 'words' list")
    out: list[dict[str, Any]] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        text = str(w.get("text") or w.get("word") or "")
        if not text:
            continue
        if "start_ms" in w or "end_ms" in w:
            start_s = float(w.get("start_ms") or 0) / 1000.0
            end_s = float(w.get("end_ms") or 0) / 1000.0
        else:
            start_s = float(w.get("start") or 0)
            end_s = float(w.get("end") or start_s)
        out.append({"text": text, "start_s": start_s, "end_s": max(end_s, start_s)})
    if not out:
        raise MapRouteError("alignment words are all empty")
    return out


def segment_end_times(
    stops: list[dict[str, Any]], words: list[dict[str, Any]]
) -> tuple[list[float | None], list[str]]:
    """End time (s) of each stop's narration segment in the alignment.

    Sequential normalised-character search: stop k's narration must appear
    after stop k-1's.  Returns (ends, notes); ``ends[k]`` is None when the
    segment was not found (caller falls back, note explains).
    """
    stream: list[tuple[str, float]] = []  # (normalised char, word end_s)
    for w in words:
        for ch in _norm(w["text"]):
            stream.append((ch, w["end_s"]))
    haystack = "".join(ch for ch, _ in stream)
    ends: list[float | None] = []
    notes: list[str] = []
    cursor = 0
    for stop in stops:
        needle = _norm(stop.get("narration") or "")
        if not needle:
            ends.append(None)
            notes.append(f"{stop['name']}: no narration segment")
            continue
        pos = haystack.find(needle, cursor)
        if pos < 0:
            ends.append(None)
            notes.append(f"{stop['name']}: narration not found in alignment")
            continue
        end_idx = pos + len(needle) - 1
        ends.append(stream[end_idx][1])
        cursor = pos + len(needle)
        notes.append(f"{stop['name']}: segment ends at {ends[-1]:.2f}s")
    return ends, notes


def build_timeline(
    stops: list[dict[str, Any]],
    stop_fractions: list[float],
    *,
    alignment: Any = None,
    total_duration_s: float | None = None,
    final_hold_s: float = 1.2,
) -> dict[str, Any]:
    """Build progress milestones [(t_s, fraction), ...] + total duration.

    ``stop_fractions[k]`` is the route fraction at stop k (0 for the first
    stop, 1 for the last).  With an alignment, the route reaches stop k at
    stop k's narration-segment end; times are forced strictly increasing
    (>= 0.4 s apart) so a cramped alignment still yields visible motion.
    ``total_duration_s`` (when given) rescales all milestone times.
    """
    if len(stops) != len(stop_fractions):
        raise MapRouteError("stops / stop_fractions length mismatch")
    notes: list[str] = []
    mode = "dwell"
    arrivals: list[float] = []

    if alignment is not None:
        words = parse_alignment(alignment)
        ends, seg_notes = segment_end_times(stops, words)
        notes.extend(seg_notes)
        if ends[0] is None:
            # The opening segment anchors departure; without it we cannot
            # trust the rest of the mapping either.
            raise MapRouteError(
                "alignment mode: first stop's narration segment not found; "
                "check that stop narrations match the aligned transcript"
            )
        mode = "alignment"
        # Fill missing middle segments by dwell-proportional interpolation
        # between the known neighbours.
        known = [i for i, e in enumerate(ends) if e is not None]
        filled: list[float] = []
        for i, e in enumerate(ends):
            if e is not None:
                filled.append(float(e))
                continue
            prev_i = max([k for k in known if k < i], default=None)
            next_i = min([k for k in known if k > i], default=None)
            if prev_i is not None and next_i is not None:
                lo, hi = float(ends[prev_i]), float(ends[next_i])  # type: ignore[arg-type]
                filled.append(lo + (hi - lo) * (i - prev_i) / (next_i - prev_i))
            elif prev_i is not None:
                filled.append(float(ends[prev_i]) + stops[i]["dwell_s"])  # type: ignore[arg-type]
            else:
                filled.append(stops[i]["dwell_s"])
            notes.append(f"{stops[i]['name']}: arrival time interpolated")
        arrivals = filled
    else:
        t = 0.0
        for stop in stops:
            t += float(stop["dwell_s"])
            arrivals.append(t)
        # arrivals[k] is when we *leave* stop k in dwell mode; the route
        # reaches stop k at the start of its dwell.  Shift: reach stop 0 at
        # t=0 (opening hold = its dwell), reach stop k at sum of dwells of
        # stops < k ... plus travel share.  Simplest consistent reading:
        # reach stop k at cumulative dwell up to and including stop k-1's
        # dwell plus half of stop k's dwell (travel), hold the rest.
        arrivals = [0.0]
        t = float(stops[0]["dwell_s"])
        for k in range(1, len(stops)):
            arrivals.append(t + 0.5 * float(stops[k]["dwell_s"]))
            t += float(stops[k]["dwell_s"])

    # Force strictly increasing arrival times.
    for i in range(1, len(arrivals)):
        if arrivals[i] <= arrivals[i - 1] + 0.4:
            arrivals[i] = arrivals[i - 1] + 0.4

    milestones: list[tuple[float, float]] = [(0.0, float(stop_fractions[0]))]
    for stop, frac, t in zip(stops, stop_fractions, arrivals):
        if t <= 0.0 and frac == stop_fractions[0]:
            continue
        milestones.append((float(t), float(frac)))
    total = milestones[-1][0] + final_hold_s
    milestones.append((total, float(stop_fractions[-1])))

    if total_duration_s is not None:
        scale = float(total_duration_s) / total if total > 0 else 1.0
        milestones = [(t * scale, f) for t, f in milestones]
        total = float(total_duration_s)

    return {
        "mode": mode,
        "milestones": milestones,
        "total_duration_s": total,
        "arrival_times_s": arrivals,
        "notes": notes,
    }


def fraction_at(milestones: list[tuple[float, float]], t_s: float) -> float:
    """Route fraction at time ``t_s`` (piecewise-linear over milestones)."""
    if t_s <= milestones[0][0]:
        return milestones[0][1]
    for i in range(1, len(milestones)):
        t1, f1 = milestones[i]
        if t_s <= t1:
            t0, f0 = milestones[i - 1]
            span = t1 - t0
            if span <= 0:
                return f1
            return f0 + (f1 - f0) * (t_s - t0) / span
    return milestones[-1][1]


__all__ = ["build_timeline", "fraction_at", "parse_alignment", "segment_end_times"]
