"""Pre-render timeline gate (``qa.timeline_gate``).

Clean-room rewrite of the *method* of the timeline check in
``win4r/video-director`` (MIT; see VIDEO_DIRECTOR_ATTRIBUTION.md):
a shot timeline is checked numerically *before* any rendering, so
a gap, a late hook, an undersized caption or a term that is
neither spoken nor shown is caught while it is still cheap to fix.
No text, code or script from the source repository is copied here;
every threshold below is a configurable default, labelled with its
method source, and hevi's existing gates stay authoritative where
they already cover the same ground (loudness, subtitle discipline,
asset registration).

Input shape (all times in seconds, sizes in pixels)::

    {
      "meta": {"w": 1920, "h": 1080, "fps": 30, "dur": 12.0,
               "clock": "music", "bpm": 120, "hookWaiver": False,
               "loop": False},
      "scenes": [{"start": 0.0, "end": 6.0}, ...],
      "beats": [0.0, 2.0, ...],
      "cuts": [6.0, ...],
      "texts": [{"role": "hook", "text": "...", "start": 0.0,
                 "end": 2.5, "px": 96}, ...],
      "terms": [{"term": "X", "said": True, "shown": True}, ...],
      "vo_words": [{"t": 0.4}, ...],
      "captions": [{"start": 0.0, "end": 1.2, "words": 3}, ...],
      "sfx": [{"at": 2.0}, ...],
      "hero": {"t": 8.0},
      "silences": [{"start": 0.0, "end": 0.6}, ...],
    }

Beats/cuts also accept ``{"at": ...}`` / ``{"t": ...}`` entries.
``texts`` entries may carry their wording under ``"text"`` or
``"content"``. ``captions`` entries may carry ``"words"`` as a
number or ``"text"`` to count from.

Verdict is ``"fail"`` when any ERROR is present and ``"pass"``
otherwise; warnings never fail the gate on their own. ``hookWaiver``
(meta) downgrades hook/CTA legibility errors to warnings.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Method defaults from the video-director timeline method, at a
# 1080-pixel short edge. Floors are scaled by the actual short edge
# (short_edge / 1080) so a vertical or smaller frame is judged on
# the same visual size, not the same raw pixel count.
REFERENCE_SHORT_EDGE = 1080.0
DEFAULT_PX_FLOORS: dict[str, float] = {"hook": 84.0, "cta": 48.0, "term": 48.0}
DEFAULT_HOOK_LEGIBLE_SEC = 3.0
DEFAULT_MIN_READ_SEC = 0.6
DEFAULT_CAPTION_MIN_SEC = 0.7
DEFAULT_CAPTION_MAX_WORDS_PER_SEC = 3.5
DEFAULT_HERO_MIN_FRACTION = 0.4
DEFAULT_SILENCE_MIN_SEC = 0.4
DEFAULT_SILENCE_WINDOW_SEC = 4.0
DEFAULT_LOOP_TOLERANCE_SEC = 0.002
DEFAULT_BEATS_PER_BAR = 4
CLOCKS = ("music", "voice", "reads")

_CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff]")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(float(value))


def _as_time(value: Any) -> float | None:
    if _is_num(value):
        return float(value)
    if isinstance(value, dict):
        for key in ("t", "at", "time", "sec", "start"):
            if _is_num(value.get(key)):
                return float(value[key])
    return None


def _word_count(text: Any) -> int:
    """Approximate word count: Latin by whitespace token, CJK per character."""
    if not isinstance(text, str):
        return 0
    stripped = text.strip()
    if not stripped:
        return 0
    tokens = stripped.split()
    cjk = len(_CJK_RE.findall(stripped))
    if cjk and len(tokens) <= 1:
        return len(stripped)
    if cjk:
        # Mixed text: whitespace tokens plus extra CJK characters
        # inside multi-character tokens.
        extra = 0
        for token in tokens:
            n = len(_CJK_RE.findall(token))
            if n > 1:
                extra += n - 1
        return len(tokens) + extra
    return len(tokens)


def read_time_required_sec(text: Any) -> float:
    """Seconds a text must be held to be read (shared hold formula).

    ``max(1.5, 1.0 + 0.3 * words)`` with CJK counted per
    character by :func:`_word_count`. This is the one formula
    every gate uses for a read hold -- the timeline gate's text
    checks, the per-shot reads list in
    ``video.segment_assembly_gate``, and the TEXTS(t) check in
    ``qa.page_contract`` -- so the three can never disagree
    about the same wording.
    """
    return max(1.5, 1.0 + 0.3 * _word_count(text))


def _text_of(entry: dict[str, Any]) -> str:
    for key in ("text", "content", "wording"):
        value = entry.get(key)
        if isinstance(value, str):
            return value
    return ""


def _silence_intervals(raw: Any) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    if not isinstance(raw, list):
        return intervals
    for entry in raw:
        if _is_num(entry):
            intervals.append((float(entry), float(entry)))
        elif isinstance(entry, dict):
            start = _as_time(entry)
            end = None
            if _is_num(entry.get("end")):
                end = float(entry["end"])
            elif _is_num(entry.get("duration")):
                end = (start or 0.0) + float(entry["duration"])
            elif _is_num(entry.get("dur")):
                end = (start or 0.0) + float(entry["dur"])
            if start is not None and end is not None:
                intervals.append((start, end))
    return intervals


def check_timeline(
    timeline: dict[str, Any],
    *,
    hook_legible_sec: float = DEFAULT_HOOK_LEGIBLE_SEC,
    px_floors: dict[str, float] | None = None,
    min_read_sec: float = DEFAULT_MIN_READ_SEC,
    caption_min_sec: float = DEFAULT_CAPTION_MIN_SEC,
    caption_max_words_per_sec: float = DEFAULT_CAPTION_MAX_WORDS_PER_SEC,
    hero_min_fraction: float = DEFAULT_HERO_MIN_FRACTION,
    silence_min_sec: float = DEFAULT_SILENCE_MIN_SEC,
    silence_window_sec: float = DEFAULT_SILENCE_WINDOW_SEC,
    loop_tolerance_sec: float = DEFAULT_LOOP_TOLERANCE_SEC,
    beats_per_bar: int = DEFAULT_BEATS_PER_BAR,
) -> dict[str, Any]:
    """Check a shot timeline dict; return errors/warnings and a verdict."""
    if not isinstance(timeline, dict):
        raise CapabilityError("qa.timeline_gate: timeline must be an object (dict)")
    floors = dict(DEFAULT_PX_FLOORS)
    if px_floors:
        floors.update(px_floors)
    errors: list[str] = []
    warnings: list[str] = []

    meta = timeline.get("meta")
    if not isinstance(meta, dict):
        errors.append("META_MISSING: meta must be an object with w/h/fps/dur/clock")
        meta = {}
    hook_waived = meta.get("hookWaiver") is True

    def _legibility(message: str) -> None:
        # Hook/CTA legibility errors downgrade to warnings under waiver.
        (warnings if hook_waived else errors).append(message)

    width = meta.get("w")
    height = meta.get("h")
    fps = meta.get("fps")
    dur = meta.get("dur")
    width_ok = _is_num(width) and float(width) > 0
    height_ok = _is_num(height) and float(height) > 0
    fps_ok = _is_num(fps) and float(fps) > 0
    dur_ok = _is_num(dur) and float(dur) > 0
    if not width_ok:
        errors.append(f"META_W: meta.w must be a positive number, got {width!r}")
    if not height_ok:
        errors.append(f"META_H: meta.h must be a positive number, got {height!r}")
    if not fps_ok:
        errors.append(f"META_FPS: meta.fps must be a positive number, got {fps!r}")
    if not dur_ok:
        errors.append(f"META_DUR: meta.dur must be a positive number, got {dur!r}")
    fps_f = float(fps) if fps_ok else None
    dur_f = float(dur) if dur_ok else None
    frame_sec = (1.0 / fps_f) if fps_f else None
    short_edge = min(float(width), float(height)) if (width_ok and height_ok) else REFERENCE_SHORT_EDGE
    px_scale = short_edge / REFERENCE_SHORT_EDGE

    clock = meta.get("clock")
    if clock not in CLOCKS:
        errors.append(f"META_CLOCK: meta.clock must be one of {list(CLOCKS)}, got {clock!r}")
    bpm = meta.get("bpm")
    bpm_ok = _is_num(bpm) and float(bpm) > 0
    if clock == "music" and not bpm_ok:
        errors.append(f"META_BPM: music clock requires a positive meta.bpm, got {bpm!r}")
    if meta.get("loop") is True and dur_ok and bpm_ok:
        bars_per = meta.get("beats_per_bar", beats_per_bar)
        bars_per_ok = _is_num(bars_per) and float(bars_per) > 0
        if not bars_per_ok:
            errors.append(f"META_LOOP: beats_per_bar must be positive, got {bars_per!r}")
        else:
            bar_sec = float(bars_per) * 60.0 / float(bpm)
            bars = float(dur) / bar_sec
            if abs(bars - round(bars)) * bar_sec > loop_tolerance_sec:
                errors.append(
                    f"LOOP_BARS: loop duration {float(dur):.3f}s is not a whole "
                    f"number of bars ({bars:.3f} bars at {float(bpm)} bpm, "
                    f"tolerance {loop_tolerance_sec}s)"
                )

    # Scenes.
    scenes = timeline.get("scenes")
    scene_spans: list[tuple[float, float]] = []
    if not isinstance(scenes, list) or not scenes:
        errors.append("SCENES_MISSING: scenes must be a non-empty list")
        scenes = []
    for idx, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"SCENE_{idx}: scene must be an object with start/end")
            continue
        start = scene.get("start")
        end = scene.get("end")
        if not _is_num(start) or not _is_num(end):
            errors.append(
                f"SCENE_{idx}: scene start/end must be numbers, "
                f"got start={start!r} end={end!r}"
            )
            continue
        if float(start) >= float(end):
            errors.append(
                f"SCENE_{idx}: scene start ({float(start)}) must be < end ({float(end)})"
            )
        scene_spans.append((float(start), float(end)))
        transition = scene.get("transitionOut", scene.get("transition_out"))
        if transition is not None:
            why = transition.get("why") if isinstance(transition, dict) else None
            if not (isinstance(why, str) and why.strip()):
                warnings.append(
                    f"TRANSITION_WHY_{idx}: scene {idx} transitionOut has no why"
                )
    if scene_spans and frame_sec is not None:
        for idx in range(len(scene_spans) - 1):
            gap = scene_spans[idx + 1][0] - scene_spans[idx][1]
            if gap > frame_sec + 1e-9:
                errors.append(
                    f"SCENE_GAP_{idx}: gap of {gap:.3f}s between scene {idx} "
                    f"and {idx + 1} exceeds one frame ({frame_sec:.3f}s)"
                )
        if dur_f is not None:
            tail_gap = abs(dur_f - scene_spans[-1][1])
            if tail_gap > frame_sec + 1e-9:
                errors.append(
                    f"SCENE_TAIL: last scene ends at {scene_spans[-1][1]:.3f}s, "
                    f"duration is {dur_f:.3f}s (gap {tail_gap:.3f}s > one frame)"
                )

    # Beats / cuts.
    def _time_list(name: str) -> list[float]:
        raw = timeline.get(name)
        if raw is None:
            return []
        if not isinstance(raw, list):
            errors.append(f"{name.upper()}_TYPE: {name} must be a list")
            return []
        times: list[float] = []
        for idx, entry in enumerate(raw):
            value = _as_time(entry)
            if value is None:
                errors.append(f"{name.upper()}_{idx}: entry is not a time, got {entry!r}")
            else:
                times.append(value)
        return times

    beats = _time_list("beats")
    cuts = _time_list("cuts")
    if dur_f is not None:
        for idx, beat in enumerate(beats):
            if beat < 0 or beat > dur_f:
                errors.append(f"BEAT_{idx}: beat at {beat:.3f}s is outside duration {dur_f:.3f}s")
        for idx, cut in enumerate(cuts):
            if cut < 0 or cut > dur_f:
                errors.append(f"CUT_{idx}: cut at {cut:.3f}s is outside duration {dur_f:.3f}s")
    for beat in beats:
        if scene_spans and not any(s <= beat <= e for s, e in scene_spans):
            warnings.append(f"BEAT_SCENE: beat at {beat:.3f}s falls outside every scene")

    # SFX must point at an existing beat.
    sfx = timeline.get("sfx", timeline.get("sound_effects", timeline.get("sfx_events")))
    if sfx is not None:
        if not isinstance(sfx, list):
            errors.append("SFX_TYPE: sfx must be a list")
        else:
            tol = frame_sec if frame_sec is not None else 0.01
            for idx, entry in enumerate(sfx):
                if not isinstance(entry, dict):
                    errors.append(f"SFX_{idx}: sfx entry must be an object, got {entry!r}")
                    continue
                if _is_num(entry.get("beat")):
                    beat_idx = int(entry["beat"])
                    if beat_idx < 0 or beat_idx >= len(beats):
                        errors.append(
                            f"SFX_{idx}: sfx beat index {beat_idx} has no matching beat"
                        )
                elif _is_num(entry.get("at")):
                    at = float(entry["at"])
                    if not any(abs(at - b) <= tol + 1e-9 for b in beats):
                        errors.append(
                            f"SFX_{idx}: sfx at {at:.3f}s points at no beat"
                        )
                else:
                    errors.append(f"SFX_{idx}: sfx entry needs a beat index or an at time")

    # Texts: legibility, size floors, read times.
    texts = timeline.get("texts")
    if texts is None:
        texts = []
    if not isinstance(texts, list):
        errors.append("TEXTS_TYPE: texts must be a list")
        texts = []
    hook_texts = [t for t in texts if isinstance(t, dict) and t.get("role") == "hook"]
    if not hook_texts:
        _legibility("HOOK_MISSING: no hook-role text in the timeline")
    for idx, entry in enumerate(texts):
        if not isinstance(entry, dict):
            errors.append(f"TEXT_{idx}: text entry must be an object")
            continue
        role = entry.get("role")
        start = entry.get("start")
        end = entry.get("end")
        if role in ("hook", "cta"):
            if not _is_num(start):
                _legibility(f"TEXT_{idx}: {role} text has no numeric start time")
            elif float(start) >= hook_legible_sec:
                _legibility(
                    f"TEXT_{idx}: {role} text starts at {float(start):.3f}s, "
                    f"not legible before {hook_legible_sec:.1f}s"
                )
        px = entry.get("px")
        if role in floors:
            floor = floors[role] * px_scale
            if _is_num(px):
                if float(px) < floor - 1e-9:
                    errors.append(
                        f"TEXT_{idx}: {role} text px {float(px):.1f} below floor "
                        f"{floor:.1f} (base {floors[role]:.0f} at 1080 short edge, "
                        f"scaled by short edge {short_edge:.0f})"
                    )
            elif px is not None:
                errors.append(f"TEXT_{idx}: {role} text px must be a number, got {px!r}")
            else:
                warnings.append(f"TEXT_{idx}: {role} text declares no px size")
        elif role is not None and px is None:
            warnings.append(f"TEXT_{idx}: role text ({role}) declares no px size")
        if _is_num(start) and _is_num(end):
            hold = float(end) - float(start)
            if hold < 0:
                errors.append(f"TEXT_{idx}: text end ({float(end)}) is before start ({float(start)})")
            else:
                if hold < min_read_sec:
                    warnings.append(
                        f"TEXT_{idx}: text held {hold:.3f}s, below read floor {min_read_sec:.1f}s"
                    )
                words = _word_count(_text_of(entry))
                required = read_time_required_sec(_text_of(entry))
                if hold < required:
                    warnings.append(
                        f"TEXT_{idx}: text held {hold:.3f}s, below read-time "
                        f"{required:.2f}s for {words} word(s)"
                    )

    # Terms: said + shown double channel.
    terms = timeline.get("terms")
    if not isinstance(terms, list) or not terms:
        warnings.append("TERMS_MISSING: no terms declared (said + shown check skipped)")
        terms = []
    for idx, entry in enumerate(terms):
        if not isinstance(entry, dict):
            errors.append(f"TERM_{idx}: term entry must be an object")
            continue
        name = entry.get("term", entry.get("name", f"term {idx}"))
        said = entry.get("said") is True
        shown = entry.get("shown") is True
        if not said and not shown:
            errors.append(f"TERM_{idx}: term {name!r} is neither said nor shown")
        elif said != shown:
            warnings.append(
                f"TERM_{idx}: term {name!r} is "
                f"{'said but not shown' if said else 'shown but not said'}"
            )

    # VO word timestamps: strictly increasing, no ESTIMATED leftovers.
    vo_words = timeline.get("vo_words")
    if vo_words is not None:
        if not isinstance(vo_words, list):
            errors.append("VO_TYPE: vo_words must be a list")
        else:
            prev: float | None = None
            for idx, entry in enumerate(vo_words):
                stamp = _as_time(entry)
                if stamp is None:
                    errors.append(f"VO_{idx}: vo word has no numeric time, got {entry!r}")
                    continue
                if prev is not None and stamp <= prev:
                    errors.append(
                        f"VO_{idx}: vo word times are not increasing "
                        f"({prev:.3f}s then {stamp:.3f}s)"
                    )
                prev = stamp
                if isinstance(entry, dict):
                    if entry.get("estimated") is True or any(
                        isinstance(v, str) and "ESTIMATED" in v for v in entry.values()
                    ):
                        warnings.append(f"VO_{idx}: vo word time is marked ESTIMATED")
            if timeline.get("vo_estimated") is True:
                warnings.append("VO_ESTIMATED: vo times are marked ESTIMATED")

    # Captions: minimum hold and words-per-second ceiling.
    captions = timeline.get("captions")
    if captions is not None:
        if not isinstance(captions, list):
            errors.append("CAPTIONS_TYPE: captions must be a list")
        else:
            for idx, entry in enumerate(captions):
                if not isinstance(entry, dict):
                    errors.append(f"CAPTION_{idx}: caption entry must be an object")
                    continue
                start = entry.get("start")
                end = entry.get("end")
                if not _is_num(start) or not _is_num(end):
                    errors.append(f"CAPTION_{idx}: caption needs numeric start/end")
                    continue
                hold = float(end) - float(start)
                if hold < caption_min_sec:
                    warnings.append(
                        f"CAPTION_{idx}: caption held {hold:.3f}s, "
                        f"below {caption_min_sec:.1f}s"
                    )
                words = entry.get("words")
                if _is_num(words):
                    count = float(words)
                else:
                    count = float(_word_count(_text_of(entry) or entry.get("words")))
                if hold > 0 and count / hold > caption_max_words_per_sec:
                    warnings.append(
                        f"CAPTION_{idx}: caption at {count / hold:.2f} words/sec, "
                        f"above {caption_max_words_per_sec:.1f}"
                    )

    # Hero and the silence before the payoff.
    hero = timeline.get("hero")
    hero_t: float | None = None
    if hero is None:
        warnings.append("HERO_MISSING: no hero declared")
    elif _is_num(hero):
        hero_t = float(hero)
    elif isinstance(hero, dict):
        hero_t = _as_time(hero)
        if hero_t is None:
            warnings.append("HERO_T_MISSING: hero declares no time")
    else:
        warnings.append(f"HERO_TYPE: hero must be a time or an object, got {hero!r}")
    if hero_t is not None and dur_f is not None and hero_t < hero_min_fraction * dur_f:
        warnings.append(
            f"HERO_EARLY: hero at {hero_t:.3f}s is before "
            f"{hero_min_fraction:.0%} of duration {dur_f:.3f}s"
        )
    silences_raw = timeline.get("silences", timeline.get("silence"))
    if silences_raw is None:
        warnings.append(
            f"SILENCE_MISSING: no silence in the first {silence_window_sec:.1f}s"
        )
    else:
        overlaps = []
        for start, end in _silence_intervals(silences_raw):
            overlap = min(end, silence_window_sec) - max(start, 0.0)
            if overlap > 0:
                overlaps.append(overlap)
        if not overlaps:
            warnings.append(
                f"SILENCE_MISSING: no silence in the first {silence_window_sec:.1f}s"
            )
        elif max(overlaps) < silence_min_sec:
            warnings.append(
                f"SILENCE_SHORT: longest silence in the first "
                f"{silence_window_sec:.1f}s is {max(overlaps):.3f}s, "
                f"below {silence_min_sec:.1f}s"
            )

    verdict = "fail" if errors else "pass"
    return {
        "capability": "qa.timeline_gate",
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "hook_waived": hook_waived,
        "thresholds": {
            "hook_legible_sec": hook_legible_sec,
            "px_floors_at_1080": floors,
            "px_scale": px_scale,
            "min_read_sec": min_read_sec,
            "caption_min_sec": caption_min_sec,
            "caption_max_words_per_sec": caption_max_words_per_sec,
            "hero_min_fraction": hero_min_fraction,
            "silence_min_sec": silence_min_sec,
            "silence_window_sec": silence_window_sec,
            "loop_tolerance_sec": loop_tolerance_sec,
            "beats_per_bar": beats_per_bar,
        },
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    for key, conv in (
        ("hook_legible_sec", float),
        ("min_read_sec", float),
        ("caption_min_sec", float),
        ("caption_max_words_per_sec", float),
        ("hero_min_fraction", float),
        ("silence_min_sec", float),
        ("silence_window_sec", float),
        ("loop_tolerance_sec", float),
    ):
        if params.get(key) is not None:
            kwargs[key] = conv(params[key])
    if params.get("px_floors") is not None:
        kwargs["px_floors"] = {str(k): float(v) for k, v in params["px_floors"].items()}
    report = check_timeline(params.get("timeline", {}), **kwargs)
    report_path = out_dir / "timeline_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "errors": report["errors"],
            "warnings": report["warnings"],
        },
    )


def register_timeline_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.timeline_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "timeline": {"type": "object"},
                    "hook_legible_sec": {"type": "number", "exclusiveMinimum": 0},
                    "min_read_sec": {"type": "number", "minimum": 0},
                    "caption_min_sec": {"type": "number", "minimum": 0},
                    "caption_max_words_per_sec": {"type": "number", "exclusiveMinimum": 0},
                    "hero_min_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                    "silence_min_sec": {"type": "number", "minimum": 0},
                    "silence_window_sec": {"type": "number", "exclusiveMinimum": 0},
                    "loop_tolerance_sec": {"type": "number", "minimum": 0},
                    "px_floors": {"type": "object"},
                },
                "required": ["timeline"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Pre-render timeline gate: scene gaps, hook/CTA legibility "
                "before 3s, text size floors scaled by short edge, term "
                "said+shown, VO timestamp order, caption speed, hero and "
                "silence checks. Errors fail; warnings do not. Thresholds "
                "are configurable method defaults (see "
                "VIDEO_DIRECTOR_ATTRIBUTION.md)."
            ),
            line="qa",
        )
    )
    return ["qa.timeline_gate"]


register_timeline_gate_capabilities_once()
