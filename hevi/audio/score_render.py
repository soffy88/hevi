"""ABC score -> locally rendered accompaniment (pure numpy, offline).

``audio.score_render`` engine: parse an ABC 2.1 subset, fit the music to
picture sync points (marks), and synthesise the result with hand-written
numpy recipes.  No network, no new dependencies, deterministic for a
given seed.

Division of labour — three different tools, no overlap
-------------------------------------------------------
* ``synth_bgm`` (``hevi/layer4_legacy/zerolines/oskill_impl/audio_math``):
  a mood-string chord pad.  Give it a mood, it drones chords; there is
  no score, no melody writing, no picture sync.
* ``procedural_bgm`` (``hevi/audio/procedural_bgm.py``): preset loop
  BGM — 5 mood presets (calm/bright/epic/tense/warm), each a fixed BPM
  + a four-bar chord-progression loop + drum pattern + pad/bass synth.
  It emits its own ``BeatGrid`` so picture can be cut *to the music*.
  Still no score input and no written melody, and the direction of fit
  is the reverse of this module's: the music is fixed, the edit follows.
* ``score_render`` (this module): the music itself is written — an ABC
  score (melody, harmony, bass, drums, dynamics, tempo shaping) or a
  direction-mode draft of one — and the tempo map is *fitted to the
  picture*: ``!mark:name!`` sync points are stretched onto the target
  times given in ``align``.

This module reuses neither of the other two: the drum recipes below
(kick/snare/hat/clap/crash) are written here, not imported from
``procedural_bgm``'s private helpers, so the three engines can evolve
independently.

Supported ABC subset (ABC 2.1)
-------------------------------
Headers: ``X:`` ``T:`` ``M:`` (incl. ``C`` / ``C|``) ``L:`` ``Q:``
(``1/4=120`` or ``120``) ``K:`` (major/minor key signatures) and ``V:``
voice definitions.  Voice attributes after the voice id:
``inst=`` (piano|pluck|strings|pad|bass|sine|drums, or a sampled
instrument name — see "Sampled timbres" below), ``role=``
(melody|harmony|bass|drums|...), ``gain=`` (float), ``transpose=``
(semitones), ``kit=`` (pop|808, drums only), ``timbre=``
(synth|sampled) and ``sampled_inst=`` (sampled instrument override).

Body: notes A-G/a-g with accidentals ``^`` ``_`` ``=`` (measure-local,
key-signature aware), octave marks ``,`` / ``'``, durations (``2``,
``/``, ``/2``, ``3/2`` relative to ``L:``), rests ``z`` / ``Z``, chords
``[CEG]``, ties ``-``, triplets ``(3``, repeats ``|:`` ``:|`` (expanded
once), inline fields ``[K:]`` ``[M:]`` ``[Q:]`` ``[L:]``, dynamics
``!pp!``..``!ff!``, hairpins ``!crescendo(!`` .. ``!crescendo)!`` /
``!diminuendo(!`` .. ``!diminuendo)!``, ``!fermata!``, ``!accent!``
(also a bare ``>``), ``!rit(!`` .. ``!rit)!``, ``!breath!`` and the
sync / impact marks below.  Unsupported decorations are ignored while
parsing but counted into the sidecar ``warnings``; grace-note groups
``{...}`` are skipped the same way.

Sync marks: ``!mark:name!`` placed at a beat tags that beat, and
``!hit!`` mixes an impact + sub-drop at that beat.  The ``!mark:name!``
convention is shared with huashu-motion's om-score so scores can move
between the two tools (convention borrowed only, no code copied;
huashu-motion by alchaincyf, MIT License).

Tempo map & fitting
-------------------
Base tempo comes from ``Q:``.  A ``rit`` span eases to 70% tempo across
the span, a fermata inserts ~0.8 beats, a breath inserts 0.18 s.
Given ``align={mark_name: seconds}`` every span between consecutive
marks is independently time-scaled so both marks land on their target
times exactly (the piecewise-linear map on the integrated base timeline
converges in one pass; residual < 5 ms by construction).  Each span's
``bend_pct`` = (target / nominal - 1) * 100; |bend| > 8% warns, which
usually means the bar count for that picture section is wrong.

Direction mode (no score)
--------------------------
``generate_score(product, scenes, style, seed)`` maps 12 product
categories to one of 4 templates (pulse / piano / cinematic / lofi),
generates an ABC text (one ``!mark:<scene-id>!`` per scene, energy ->
dynamics & density, a rest bar before the drop scene and ``!hit!`` on
the drop), and the caller feeds it through the exact same
parse -> fit -> render pipeline.

Mastering constants: RMS target -18 dBFS, peak ceiling -1.5 dBFS,
output 48 kHz 16-bit stereo WAV by default.

Sampled timbres (real instruments)
----------------------------------
The synth recipes above are the default and the fallback.  A voice can
instead be played from the vendored VCSL sample library (CC0 samples
curated by mg-styles-15, MIT; see ``hevi/audio/sampled_data/`` and
:mod:`hevi.audio.sampled`):

* per-voice ABC attributes: ``timbre=sampled`` (or ``timbre=synth`` to
  force the recipes) and ``sampled_inst=<name>`` to name the sampled
  instrument directly (piano / marimba / vibraphone / harp / glock /
  kalimba / wineglass; one-shots for drum voices).  Naming a sampled
  instrument in ``inst=`` (e.g. ``inst=marimba``) also selects the
  sampled path for that voice, since the synth has no such recipe.
* per-render: ``render_score(..., timbre="sampled")`` switches every
  voice; ``timbre="synth"`` forces recipes.  Default ``None`` keeps the
  historical behaviour (synth, except ``inst=``-named sampled-only
  instruments above).
* without ``sampled_inst=``, a synth voice name is mapped to its
  sampled counterpart (piano->piano, pluck->kalimba, strings->harp,
  pad->vibraphone, bass->piano, sine->wineglass); unmapped voices and
  any sample-library failure fall back to the synth recipe for that
  note, with a sidecar ``warnings`` entry — rendering never fakes a
  sampled note it did not play.  The fit/align pipeline, timing jitter
  and mastering are shared unchanged, and picking is a pure function,
  so same seed + same input renders byte-identical audio on both
  paths.  The sidecar reports ``engine`` as ``numpy_synth`` /
  ``sampled`` / ``sampled+synth`` plus a per-voice ``timbre`` and a
  ``sampled`` summary (instruments used, note counts).
"""

from __future__ import annotations

import contextlib
import itertools
import math
import re
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

TARGET_RMS_DBFS = -18.0
PEAK_LIMIT_DBFS = -1.5
DEFAULT_SAMPLE_RATE = 48000
RIT_MIN_TEMPO_FACTOR = 0.70
FERMATA_EXTRA_BEATS = 0.8
BREATH_EXTRA_S = 0.18
FIT_TOLERANCE_S = 0.005

__all__ = [
    "PEAK_LIMIT_DBFS",
    "PRODUCT_MAP",
    "TARGET_RMS_DBFS",
    "TEMPLATES",
    "ScoreRenderError",
    "build_time_map",
    "generate_score",
    "parse_abc",
    "render_score",
]


class ScoreRenderError(ValueError):
    """Raised for un-parseable scores / impossible alignment requests."""


# --------------------------------------------------------------------------
# Key signatures
# --------------------------------------------------------------------------

_LETTER_SEMI = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SHARP_ORDER = ["F", "C", "G", "D", "A", "E", "B"]
_FLAT_ORDER = ["B", "E", "A", "D", "G", "C", "F"]
_MAJOR_SHARPS = {"G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7}
_MAJOR_FLATS = {"F": 1, "Bb": 2, "Eb": 3, "Ab": 4, "Db": 5, "Gb": 6}


def _key_signature(key: str) -> dict[str, int]:
    """Letter -> accidental offset implied by a key string like 'G'/'Am'."""
    k = key.strip()
    if not k:
        raise ScoreRenderError("empty K: field")
    minor = False
    m = re.match(r"^([A-G])([#b]?)\s*(.*)$", k)
    if not m:
        raise ScoreRenderError(f"bad key signature: {key!r}")
    tonic = m.group(1) + m.group(2)
    rest = m.group(3).strip().lower()
    if rest.startswith("m") and not rest.startswith("maj"):
        minor = True
    if minor:  # relative major is a minor third up
        idx = list(_LETTER_SEMI).index(m.group(1))
        rel_letter = list(_LETTER_SEMI)[(idx + 2) % 7]
        # semitone-accurate relative major tonic (only name matters here)
        semi = (_LETTER_SEMI[m.group(1)] + {"#": 1, "b": -1, "": 0}[m.group(2)] + 3) % 12
        tonic = rel_letter
        for cand, s in _LETTER_SEMI.items():
            if s == semi:
                tonic = cand
        if semi == (_LETTER_SEMI[rel_letter] + 1) % 12:
            tonic = rel_letter + "#"
        elif semi == (_LETTER_SEMI[rel_letter] - 1) % 12:
            tonic = rel_letter + "b"
    sig: dict[str, int] = {}
    if tonic in _MAJOR_SHARPS:
        for letter in _SHARP_ORDER[: _MAJOR_SHARPS[tonic]]:
            sig[letter] = 1
    elif tonic in _MAJOR_FLATS:
        for letter in _FLAT_ORDER[: _MAJOR_FLATS[tonic]]:
            sig[letter] = -1
    elif tonic != "C":
        raise ScoreRenderError(f"unsupported key signature: {key!r}")
    return sig


def _parse_fraction(text: str, default: float) -> float:
    text = text.strip()
    if not text:
        return default
    if "/" in text:
        a, b = text.split("/", 1)
        return float(a or 1) / float(b or 2)
    return float(text)


def _parse_meter(text: str) -> float:
    """Return beats (quarter notes) per measure."""
    t = text.strip()
    if t in ("C",):
        return 4.0
    if t in ("C|",):
        return 2.0
    if "/" in t:
        num, den = t.split("/", 1)
        return float(num) * (4.0 / float(den))
    return 4.0


def _parse_tempo(text: str) -> float:
    """Return BPM (quarter-note beats per minute) from a Q: value."""
    t = text.strip()
    if "=" in t:
        t = t.split("=", 1)[1].strip()
    m = re.search(r"(\d+(?:\.\d+)?)", t)
    if not m:
        raise ScoreRenderError(f"bad tempo: {text!r}")
    bpm = float(m.group(1))
    if bpm <= 0:
        raise ScoreRenderError(f"bad tempo: {text!r}")
    return bpm


# --------------------------------------------------------------------------
# Parsed model
# --------------------------------------------------------------------------


@dataclass
class VoiceDef:
    vid: str
    inst: str = "piano"
    role: str = ""
    gain: float = 1.0
    transpose: int = 0
    kit: str = "pop"
    timbre: str = ""  # "" = render default, else "synth" | "sampled"
    sampled_inst: str = ""  # sampled instrument override (timbre=sampled)


@dataclass
class NoteEvent:
    voice: str
    midi: int | None  # None = rest
    start_beat: float
    dur_beats: float
    velocity: int = 85
    chord_id: int = -1  # >=0 groups simultaneous chord tones
    tie: bool = False
    staccato: bool = False


@dataclass
class ParsedScore:
    title: str = ""
    bpm: float = 120.0
    meter_beats: float = 4.0
    voices: dict[str, VoiceDef] = field(default_factory=dict)
    events: list[NoteEvent] = field(default_factory=list)
    marks: dict[str, float] = field(default_factory=dict)  # name -> beat
    hits: list[float] = field(default_factory=list)  # beats
    rit_spans: list[tuple[float, float]] = field(default_factory=list)
    fermata_beats: list[float] = field(default_factory=list)
    breath_beats: list[float] = field(default_factory=list)
    tempo_changes: dict[float, float] = field(default_factory=dict)  # beat->bpm
    total_beats: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def note_count(self, vid: str | None = None) -> int:
        return sum(
            1
            for e in self.events
            if e.midi is not None and (vid is None or e.voice == vid)
        )


_DYNAMICS = {
    "ppp": 30, "pp": 42, "p": 55, "mp": 68,
    "mf": 82, "f": 96, "ff": 110, "fff": 122,
    "sfz": 118, "sf": 112,
}


def _parse_voice_attrs(text: str, vd: VoiceDef) -> None:
    for tok in text.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            k = k.strip().lower()
            v = v.strip().strip('"')
            if k == "inst":
                vd.inst = v.lower()
            elif k == "timbre":
                if v.lower() in ("synth", "sampled"):
                    vd.timbre = v.lower()
            elif k == "sampled_inst":
                vd.sampled_inst = v.lower()
            elif k == "role":
                vd.role = v.lower()
            elif k == "kit":
                vd.kit = v.lower()
            elif k == "gain":
                with contextlib.suppress(ValueError):
                    vd.gain = float(v)
            elif k == "transpose":
                with contextlib.suppress(ValueError):
                    vd.transpose = int(v)
            # clef=, name=, etc. are display-only here: accepted, ignored.


class _VoiceParser:
    def __init__(self, score: ParsedScore, vd: VoiceDef, state: dict[str, Any]):
        self.score = score
        self.vd = vd
        self.key_str = state["key"]
        self.key_sig = _key_signature(state["key"])
        self.meter_beats = state["meter_beats"]
        self.unit_beats = state["unit_beats"]  # quarter beats per L unit
        self.cursor = 0.0
        self.measure_acc: dict[str, int] = {}
        self.velocity = 82
        self.pending_accent = False
        self.pending_fermata = False
        self.triplet_left = 0
        self.events: list[NoteEvent] = []
        self.repeat_start_idx = 0
        self.repeat_start_cursor = 0.0
        self.repeated = False
        self.chord_seq = 0
        self.hairpin: tuple[str, float] | None = None  # (kind, start_beat)
        self.rit_start: float | None = None
        # crescendo/diminuendo velocity ramps: (vstart, vend, start, end)
        self.ramps: list[tuple[int, int, float, float]] = []

    # -- duration suffix -------------------------------------------------
    def _read_duration(self, s: str, i: int) -> tuple[float, int]:
        """Duration in beats for the token ending just before index i."""
        start = i
        num = ""
        while i < len(s) and s[i].isdigit():
            num += s[i]
            i += 1
        den = ""
        slashes = 0
        while i < len(s) and s[i] == "/":
            slashes += 1
            i += 1
            while i < len(s) and s[i].isdigit():
                den += s[i]
                i += 1
        if num and slashes:
            mult = float(num) / float(den or (2**slashes))
        elif num:
            mult = float(num)
        elif slashes:
            mult = 1.0 / float(den or (2**slashes))
        else:
            mult = 1.0
        _ = start
        return mult * self.unit_beats, i

    def _apply_triplet(self, dur: float) -> float:
        if self.triplet_left > 0:
            self.triplet_left -= 1
            return dur * (2.0 / 3.0)
        return dur

    def _velocity_at(self, beat: float) -> int:
        v = self.velocity
        for v0, v1, b0, b1 in self.ramps:
            if b0 <= beat <= b1 and b1 > b0:
                v = round(v0 + (v1 - v0) * (beat - b0) / (b1 - b0))
        if self.pending_accent:
            v = min(127, v + 22)
        return max(1, min(127, v))

    def _emit(self, midi: int | None, dur: float, chord_id: int = -1) -> NoteEvent:
        ev = NoteEvent(
            voice=self.vd.vid,
            midi=midi,
            start_beat=self.cursor,
            dur_beats=dur,
            velocity=self._velocity_at(self.cursor) if midi is not None else 0,
            chord_id=chord_id,
        )
        self.events.append(ev)
        self.pending_accent = False
        if self.pending_fermata and midi is not None:
            self.score.fermata_beats.append(self.cursor + dur)
            self.pending_fermata = False
        self.cursor += dur
        return ev

    # -- decorations -----------------------------------------------------
    def _decoration(self, name: str) -> None:
        low = name.strip()
        if low in _DYNAMICS:
            self.velocity = _DYNAMICS[low]
        elif low.startswith("mark:"):
            mark = low[5:].strip()
            if mark:
                if mark in self.score.marks and self.score.marks[mark] != self.cursor:
                    self.score.warnings.append(f"duplicate mark {mark!r} kept first")
                else:
                    self.score.marks.setdefault(mark, self.cursor)
        elif low == "hit":
            self.score.hits.append(self.cursor)
        elif low == "fermata":
            self.pending_fermata = True
        elif low in ("accent", "marcato"):
            self.pending_accent = True
        elif low == "breath":
            self.score.breath_beats.append(self.cursor)
        elif low in ("crescendo(", "diminuendo("):
            kind = "crescendo" if low.startswith("crescendo") else "diminuendo"
            self.hairpin = (kind, self.cursor)
        elif low in ("crescendo)", "diminuendo)"):
            if self.hairpin is not None:
                kind, b0 = self.hairpin
                delta = 24 if kind == "crescendo" else -24
                self.ramps.append(
                    (self.velocity, max(1, min(127, self.velocity + delta)), b0, self.cursor)
                )
                self.hairpin = None
        elif low == "rit(":
            self.rit_start = self.cursor
        elif low == "rit)":
            if self.rit_start is not None:
                self.score.rit_spans.append((self.rit_start, self.cursor))
                self.rit_start = None
        elif low in ("rit", "ritard", "rall"):
            self.score.warnings.append("bare !rit! without span treated as no-op")
        else:
            self.score.warnings.append(f"unsupported decoration !{name}! ignored")

    # -- inline fields ---------------------------------------------------
    def _inline_field(self, content: str) -> None:
        m = re.match(r"^([A-Za-z]):(.*)$", content.strip())
        if not m:
            return
        field_name, value = m.group(1).upper(), m.group(2).strip()
        try:
            if field_name == "K":
                self.key_str = value
                self.key_sig = _key_signature(value)
                self.measure_acc.clear()
            elif field_name == "M":
                self.meter_beats = _parse_meter(value)
            elif field_name == "L":
                self.unit_beats = _parse_fraction(value, 0.25) * 4.0
            elif field_name == "Q":
                self.score.tempo_changes[self.cursor] = _parse_tempo(value)
            elif field_name == "V":
                parts = value.split(None, 1)
                if parts:
                    vd = self.score.voices.setdefault(parts[0], VoiceDef(parts[0]))
                    if len(parts) > 1:
                        _parse_voice_attrs(parts[1], vd)
        except ScoreRenderError:
            raise
        except Exception as exc:
            raise ScoreRenderError(f"bad inline field [{content}]: {exc}") from exc

    # -- main scan ---------------------------------------------------------
    def parse(self, s: str) -> None:
        i, n = 0, len(s)
        explicit_acc: int | None = None
        while i < n:
            c = s[i]
            if c in " \t\r":
                i += 1
                continue
            if c == "\n":
                i += 1
                continue
            if c == "%":
                while i < n and s[i] != "\n":
                    i += 1
                continue
            if c == '"':  # chord symbol / annotation string
                i += 1
                while i < n and s[i] != '"':
                    i += 1
                i += 1
                continue
            if c == "!":
                j = s.find("!", i + 1)
                if j == -1:
                    raise ScoreRenderError("unterminated !decoration!")
                self._decoration(s[i + 1 : j])
                i = j + 1
                continue
            if c == ">":
                self.pending_accent = True
                i += 1
                continue
            if c in "<.":
                if c == ".":
                    pass  # staccato dot: accepted, envelope already short for pluck
                i += 1
                continue
            if c == "{":
                j = s.find("}", i + 1)
                if j == -1:
                    raise ScoreRenderError("unterminated grace-note group")
                self.score.warnings.append("grace notes {...} skipped (unsupported)")
                i = j + 1
                continue
            if c == "(":
                if i + 1 < n and s[i + 1].isdigit():
                    j = i + 1
                    num = ""
                    while j < n and (s[j].isdigit() or s[j] == ":"):
                        if s[j].isdigit():
                            num += s[j]
                        j += 1
                    self.triplet_left = int(num or 3)
                    i = j
                else:
                    i += 1  # slur open
                continue
            if c == ")":
                i += 1  # slur close
                continue
            if c == "-":
                if self.events:
                    self.events[-1].tie = True
                i += 1
                continue
            if c == "|":
                # barline variants; repeats first
                if s[i : i + 2] == "|:":
                    self.repeat_start_idx = len(self.events)
                    self.repeat_start_cursor = self.cursor
                    self.repeated = False
                    i += 2
                elif s[i : i + 2] in (":|", ":]"):
                    self._do_repeat()
                    i += 2
                else:
                    i += 1
                    while i < n and s[i] in "|]:":
                        if s[i] == ":" and i + 1 < n and s[i + 1] == "|":
                            break
                        i += 1
                self.measure_acc.clear()
                explicit_acc = None
                continue
            if c == ":":
                if s[i : i + 2] == ":|":
                    self._do_repeat()
                    i += 2
                    self.measure_acc.clear()
                    continue
                i += 1
                continue
            if c == "[":
                # inline field?
                m = re.match(r"\[([A-Za-z]):", s[i:])
                if m:
                    j = s.find("]", i)
                    if j == -1:
                        raise ScoreRenderError("unterminated inline field")
                    self._inline_field(s[i + 1 : j])
                    i = j + 1
                    continue
                # chord
                j = s.find("]", i)
                if j == -1:
                    raise ScoreRenderError("unterminated chord [...]")
                inner = s[i + 1 : j]
                midis = self._parse_chord_inner(inner)
                dur, i2 = self._read_duration(s, j + 1)
                dur = self._apply_triplet(dur)
                if midis:
                    self.chord_seq += 1
                    for midi in sorted(midis):
                        ev = NoteEvent(
                            voice=self.vd.vid,
                            midi=midi,
                            start_beat=self.cursor,
                            dur_beats=dur,
                            velocity=self._velocity_at(self.cursor),
                            chord_id=self.chord_seq,
                        )
                        self.events.append(ev)
                    self.pending_accent = False
                    if self.pending_fermata:
                        self.score.fermata_beats.append(self.cursor + dur)
                        self.pending_fermata = False
                    self.cursor += dur
                else:
                    self.cursor += dur
                i = i2
                explicit_acc = None
                continue
            if c in "^_=":
                acc = 0
                if c == "=":
                    explicit_acc = 0
                    i += 1
                else:
                    # ^ ^_ etc: consume run
                    val = 1 if c == "^" else -1
                    acc = val
                    i += 1
                    while i < n and s[i] in "^_":
                        acc += 1 if s[i] == "^" else -1
                        i += 1
                    explicit_acc = acc
                continue
            if c in "zZx":
                bare_measure = c == "Z"
                dur, i = self._read_duration(s, i + 1)
                if bare_measure and dur == self.unit_beats:
                    dur = self.meter_beats  # Z with no number = full measure
                dur = self._apply_triplet(dur)
                self._emit(None, dur)
                explicit_acc = None
                continue
            if c.isalpha() and c.upper() in _LETTER_SEMI:
                letter = c.upper()
                if explicit_acc is not None:
                    acc_off = explicit_acc
                    self.measure_acc[letter] = acc_off
                else:
                    acc_off = self.measure_acc.get(
                        letter, self.key_sig.get(letter, 0)
                    )
                midi = 60 + _LETTER_SEMI[letter] + acc_off
                if c.islower():
                    midi += 12
                i += 1
                while i < n and s[i] in ",'":
                    midi += -12 if s[i] == "," else 12
                    i += 1
                dur, i = self._read_duration(s, i)
                dur = self._apply_triplet(dur)
                self._emit(midi + self.vd.transpose, dur)
                explicit_acc = None
                continue
            # Anything else (digits standing alone, '/', '\\', etc.) is skipped.
            i += 1
        if self.pending_fermata:
            self.score.fermata_beats.append(self.cursor)
            self.pending_fermata = False

    def _parse_chord_inner(self, inner: str) -> list[int]:
        midis: list[int] = []
        i, n = 0, len(inner)
        acc: int | None = None
        while i < n:
            ch = inner[i]
            if ch in "^_":
                val = 1 if ch == "^" else -1
                acc = val if acc is None else acc + val
                i += 1
                continue
            if ch == "=":
                acc = 0
                i += 1
                continue
            if ch.isalpha() and ch.upper() in _LETTER_SEMI:
                letter = ch.upper()
                if acc is not None:
                    off = acc
                    self.measure_acc[letter] = off
                else:
                    off = self.measure_acc.get(letter, self.key_sig.get(letter, 0))
                midi = 60 + _LETTER_SEMI[letter] + off
                if ch.islower():
                    midi += 12
                i += 1
                while i < n and inner[i] in ",'":
                    midi += -12 if inner[i] == "," else 12
                    i += 1
                # per-note length inside a chord is meaningless here; skip digits
                while i < n and (inner[i].isdigit() or inner[i] == "/"):
                    i += 1
                midis.append(midi + self.vd.transpose)
                acc = None
                continue
            i += 1
        return midis

    def _do_repeat(self) -> None:
        if self.repeated:
            return
        self.repeated = True
        seg = self.events[self.repeat_start_idx :]
        span = self.cursor - self.repeat_start_cursor
        if span <= 0 or not seg:
            return
        for ev in list(seg):
            self.events.append(
                NoteEvent(
                    voice=ev.voice,
                    midi=ev.midi,
                    start_beat=ev.start_beat + span,
                    dur_beats=ev.dur_beats,
                    velocity=ev.velocity,
                    chord_id=ev.chord_id,
                    tie=ev.tie,
                )
            )
        self.cursor += span


def _merge_ties(events: list[NoteEvent]) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    for ev in events:
        if (
            out
            and out[-1].tie
            and out[-1].midi is not None
            and ev.midi == out[-1].midi
            and ev.voice == out[-1].voice
        ):
            out[-1].dur_beats += ev.dur_beats
            out[-1].tie = ev.tie
            continue
        out.append(ev)
    for ev in out:
        ev.tie = False
    return out


_HEADER_RE = re.compile(r"^([A-Za-z]):\s?(.*)$")


def parse_abc(text: str) -> ParsedScore:
    """Parse the supported ABC subset; ScoreRenderError on bad input."""
    if not text or not text.strip():
        raise ScoreRenderError("empty ABC score")
    score = ParsedScore()
    state: dict[str, Any] = {
        "key": None,
        "meter_beats": 4.0,
        "unit_beats": 0.5,  # L:1/8 default when the tune is short-note based
        "unit_set": False,
    }
    bpm = 120.0
    current_vid = "1"
    score.voices[current_vid] = VoiceDef(current_vid)
    bodies: dict[str, list[str]] = {current_vid: []}
    body_started = False
    saw_key = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%"):
            continue
        m = _HEADER_RE.match(line)
        if m and m.group(1) == "V":
            rest = m.group(2).strip()
            parts = rest.split(None, 1)
            if not parts:
                raise ScoreRenderError("V: line without a voice id")
            current_vid = parts[0]
            vd = score.voices.setdefault(current_vid, VoiceDef(current_vid))
            if len(parts) > 1:
                _parse_voice_attrs(parts[1], vd)
            bodies.setdefault(current_vid, [])
            continue
        if m and not body_started and m.group(1) in "XTMLQK":
            fname, value = m.group(1), m.group(2).strip()
            try:
                if fname == "T":
                    score.title = value
                elif fname == "M":
                    state["meter_beats"] = _parse_meter(value)
                    score.meter_beats = state["meter_beats"]
                elif fname == "L":
                    state["unit_beats"] = _parse_fraction(value, 0.125) * 4.0
                    state["unit_set"] = True
                elif fname == "Q":
                    bpm = _parse_tempo(value)
                elif fname == "K":
                    _key_signature(value)  # validate eagerly = bad header fails
                    state["key"] = value
                    saw_key = True
            except ScoreRenderError:
                raise
            except Exception as exc:
                raise ScoreRenderError(f"bad header {fname}: {value!r}: {exc}") from exc
            continue
        if m and m.group(1) in "Ww":
            continue  # lyrics / words: not music
        body_started = True
        bodies.setdefault(current_vid, []).append(line)

    if not saw_key and state["key"] is None:
        raise ScoreRenderError("bad header: missing K: (key) field")
    if not state["unit_set"]:
        # ABC default: L=1/8 when shortest notes are short, else 1/4-ish.
        # Our generator/tests always set L:; keep 1/8 spec default.
        state["unit_beats"] = 0.5
    score.bpm = bpm
    state["bpm"] = bpm

    any_notes = False
    for vid, lines in bodies.items():
        if not lines:
            continue
        vd = score.voices[vid]
        parser = _VoiceParser(score, vd, {
            "key": state["key"],
            "meter_beats": state["meter_beats"],
            "unit_beats": state["unit_beats"],
        })
        parser.parse("\n".join(lines))
        score.events.extend(parser.events)
        score.total_beats = max(score.total_beats, parser.cursor)
        if any(e.midi is not None for e in parser.events):
            any_notes = True
    score.events = _merge_ties(
        sorted(score.events, key=lambda e: (e.start_beat, e.voice, e.midi or -1))
    )
    if not any_notes:
        raise ScoreRenderError("ABC score contains no notes")
    if score.total_beats <= 0:
        raise ScoreRenderError("ABC score has zero duration")
    return score


# --------------------------------------------------------------------------
# Tempo map + mark fitting
# --------------------------------------------------------------------------


class TimeMap:
    """Integrated base timeline + per-span mark fitting (piecewise linear)."""

    def __init__(self, score: ParsedScore, align: dict[str, float] | None):
        self.score = score
        total = max(score.total_beats, 0.001)
        self._grid_step = 0.01
        grid = np.arange(0.0, total + self._grid_step, self._grid_step)
        # tempo at each grid beat
        bpm_arr = np.full_like(grid, score.bpm, dtype=np.float64)
        for beat, bpm in sorted(score.tempo_changes.items()):
            bpm_arr[grid >= beat - 1e-9] = bpm
        spb = 60.0 / bpm_arr
        mult = np.ones_like(grid)
        for b0, b1 in score.rit_spans:
            if b1 <= b0:
                continue
            in_span = (grid >= b0) & (grid <= b1)
            prog = np.clip((grid[in_span] - b0) / (b1 - b0), 0.0, 1.0)
            factor = 1.0 - (1.0 - RIT_MIN_TEMPO_FACTOR) * prog
            mult[in_span] = 1.0 / factor
        seg = spb * mult * self._grid_step
        cum = np.concatenate([[0.0], np.cumsum(seg)])[: len(grid)]
        # cum[k] approximates integral up to grid[k]; shift so cum[0]=0
        self._grid = grid
        self._cum = cum
        self._fermata = sorted(score.fermata_beats)
        self._breath = sorted(score.breath_beats)
        self._spb0 = 60.0 / score.bpm

        align = dict(align or {})
        for name in align:
            if name not in score.marks:
                raise ScoreRenderError(
                    f"align references unknown mark {name!r}; "
                    f"score marks: {sorted(score.marks)}"
                )
        anchors = sorted(
            ((score.marks[name], float(t), name) for name, t in align.items()),
            key=lambda x: x[0],
        )
        targets = [t for _, t, _ in anchors]
        if any(b <= a for a, b in itertools.pairwise(targets)):
            raise ScoreRenderError("align mark times must be strictly increasing")
        self.anchors = anchors
        self.stretches: list[dict[str, Any]] = []
        self.warnings: list[str] = []
        self._seg_scales: list[float] = []
        for (b0, t0, n0), (b1, t1, n1) in itertools.pairwise(anchors):
            nom = self.base_time(b1) - self.base_time(b0)
            tar = t1 - t0
            scale = (tar / nom) if nom > 1e-9 else 1.0
            if tar <= 0:
                raise ScoreRenderError("align mark times must be strictly increasing")
            bend = (scale - 1.0) * 100.0
            self._seg_scales.append(scale)
            self.stretches.append(
                {"from": n0, "to": n1, "bend_pct": round(bend, 3)}
            )
            if abs(bend) > 8.0:
                self.warnings.append(
                    f"stretch {n0}->{n1} bend {bend:+.1f}% exceeds 8% "
                    "(bar count for this section probably does not match picture)"
                )
        self._single_scale: float | None = None
        if len(anchors) == 1:
            b0, t0, _ = anchors[0]
            base0 = self.base_time(b0)
            if base0 > 1e-9:
                self._single_scale = t0 / base0
            else:
                self._single_scale = 1.0

    def base_time(self, beat: float) -> float:
        t = float(np.interp(beat, self._grid, self._cum))
        for pos in self._fermata:
            if beat >= pos - 1e-9:
                t += FERMATA_EXTRA_BEATS * self._spb0
        for pos in self._breath:
            if beat >= pos - 1e-9:
                t += BREATH_EXTRA_S
        return t

    def time(self, beat: float) -> float:
        if not self.anchors:
            return self.base_time(beat)
        if len(self.anchors) == 1:
            b0, t0, _ = self.anchors[0]
            return t0 + (self.base_time(beat) - self.base_time(b0)) * (
                self._single_scale or 1.0
            )
        first_b, first_t, _ = self.anchors[0]
        last_b, last_t, _ = self.anchors[-1]
        if beat <= first_b:
            scale = self._seg_scales[0]
            return first_t - (self.base_time(first_b) - self.base_time(beat)) * scale
        if beat >= last_b:
            scale = self._seg_scales[-1]
            return last_t + (self.base_time(beat) - self.base_time(last_b)) * scale
        for idx, ((b0, t0, _), (b1, _t1, _)) in enumerate(
            itertools.pairwise(self.anchors)
        ):
            if b0 <= beat <= b1:
                scale = self._seg_scales[idx]
                return t0 + (self.base_time(beat) - self.base_time(b0)) * scale
        return self.base_time(beat)  # pragma: no cover


def build_time_map(
    score: ParsedScore, align: dict[str, float] | None
) -> TimeMap:
    return TimeMap(score, align)


# --------------------------------------------------------------------------
# Synthesis recipes (numpy)
# --------------------------------------------------------------------------


def _midi_freq(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _synth_note(
    inst: str, midi: int, dur_s: float, vel: int, sr: int, rng_tail: float = 0.0
) -> np.ndarray:
    freq = _midi_freq(midi)
    if inst == "piano":
        length = dur_s + 1.2
        t = np.arange(int(length * sr)) / sr
        amps = [1.0, 0.55, 0.32, 0.18, 0.10, 0.06]
        tau = float(np.clip(0.9 * math.sqrt(440.0 / max(freq, 20.0)) + 0.35, 0.35, 2.2))
        env = (1 - np.exp(-t / 0.004)) * np.exp(-t / tau)
        wave_ = np.zeros_like(t)
        for k, a in enumerate(amps, start=1):
            wave_ += a * np.sin(2 * np.pi * freq * k * (1 + 0.0002 * k * k) * t)
        return wave_ * env
    if inst == "pluck":
        length = dur_s + 0.35
        t = np.arange(int(length * sr)) / sr
        wave_ = np.zeros_like(t)
        for k in range(1, 7):
            wave_ += (1.0 / k) * np.sin(2 * np.pi * freq * k * t) * np.exp(
                -t / (0.38 / k**0.5)
            )
        env = 1 - np.exp(-t / 0.002)
        return wave_ * env
    if inst in ("strings", "pad"):
        length = dur_s + 0.45
        t = np.arange(int(length * sr)) / sr
        attack = np.clip(t / 0.22, 0, 1)
        release = np.clip((length - t) / 0.4, 0, 1)
        env = attack * np.minimum(1.0, release + 0.15)
        vib = 1.0 + 0.003 * np.sin(2 * np.pi * 5.0 * t)
        wave_ = np.zeros_like(t)
        for k, a in enumerate([1.0, 0.5, 0.33, 0.22, 0.14], start=1):
            wave_ += a * np.sin(2 * np.pi * freq * k * vib * t)
        return wave_ * env * 0.7
    if inst == "bass":
        length = dur_s + 0.3
        t = np.arange(int(length * sr)) / sr
        env = (1 - np.exp(-t / 0.008)) * (0.55 + 0.45 * np.exp(-t / max(dur_s, 0.3)))
        return env * (
            np.sin(2 * np.pi * freq * t)
            + 0.35 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.12 * np.sin(2 * np.pi * freq * 3 * t)
        )
    # sine and fallback: pure tone bed
    length = dur_s + 0.3
    t = np.arange(int(length * sr)) / sr
    env = (1 - np.exp(-t / 0.02)) * np.exp(-t / max(dur_s + 0.25, 0.4))
    return np.sin(2 * np.pi * freq * t) * env


# GM subset used by drum voices: midi -> drum name
_GM_DRUMS = {35: "kick", 36: "kick", 38: "snare", 40: "snare", 39: "clap",
             42: "hat", 44: "hat", 46: "hat_open", 49: "crash", 57: "crash"}


def _synth_drum(
    name: str, kit: str, sr: int, rng: np.random.Generator, vel: int
) -> np.ndarray:
    v = vel / 127.0
    if name == "kick":
        dur = 0.28 if kit != "808" else 0.5
        t = np.arange(int(dur * sr)) / sr
        f0 = 130.0 if kit != "808" else 110.0
        freq = 42.0 + (f0 - 42.0) * np.exp(-t / 0.045)
        phase = np.cumsum(freq) / sr * 2 * np.pi
        return np.sin(phase) * np.exp(-t / (0.11 if kit != "808" else 0.22)) * v
    if name == "snare":
        dur = 0.2
        t = np.arange(int(dur * sr)) / sr
        noise = rng.standard_normal(len(t))
        hp = np.concatenate([[noise[0]], np.diff(noise)])
        return (hp * 0.7 * np.exp(-t / 0.06) + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t / 0.04)) * v
    if name in ("hat", "hat_open"):
        dur = 0.05 if name == "hat" else 0.3
        if kit == "808":
            dur *= 1.4
        t = np.arange(int(dur * sr)) / sr
        noise = rng.standard_normal(len(t))
        hp = np.concatenate([[noise[0]], np.diff(noise)])
        return hp * np.exp(-t / (dur / 3.0)) * 0.55 * v
    if name == "clap":
        dur = 0.22
        t = np.arange(int(dur * sr)) / sr
        noise = rng.standard_normal(len(t))
        hp = np.concatenate([[noise[0]], np.diff(noise)])
        pulses = np.zeros_like(t)
        for p in (0.0, 0.012, 0.025):
            pulses += np.exp(-np.abs(t - p) / 0.006)
        pulses += 0.6 * np.exp(-(t - 0.04) / 0.07) * (t >= 0.04)
        return hp * np.clip(pulses, 0, 1.4) * 0.6 * v
    if name == "crash":
        dur = 1.4
        t = np.arange(int(dur * sr)) / sr
        noise = rng.standard_normal(len(t))
        hp = np.concatenate([[noise[0]], np.diff(noise)])
        return hp * np.exp(-t / 0.45) * 0.5 * v
    return np.zeros(1)


def _synth_hit(sr: int, rng: np.random.Generator) -> np.ndarray:
    dur = 0.9
    t = np.arange(int(dur * sr)) / sr
    freq = 30.0 + 130.0 * np.exp(-t / 0.08)
    phase = np.cumsum(freq) / sr * 2 * np.pi
    impact = np.sin(phase) * np.exp(-t / 0.28)
    sub_freq = 28.0 + 30.0 * np.exp(-t / 0.25)
    sub_phase = np.cumsum(sub_freq) / sr * 2 * np.pi
    sub = np.sin(sub_phase) * np.exp(-t / 0.5) * 0.9
    noise = rng.standard_normal(len(t))
    hp = np.concatenate([[noise[0]], np.diff(noise)])
    burst = hp * np.exp(-t / 0.03) * 0.5
    return impact + sub + burst


def _add_stereo(
    mix: np.ndarray, mono: np.ndarray, start: int, pan: float, gain: float
) -> None:
    if start >= len(mix):
        return
    end = min(len(mix), start + len(mono))
    if end <= start:
        return
    seg = mono[: end - start] * gain
    left = math.cos((pan + 1) * math.pi / 4)
    right = math.sin((pan + 1) * math.pi / 4)
    mix[start:end, 0] += seg * left
    mix[start:end, 1] += seg * right


def _write_wav(path: Path, mix: np.ndarray, sr: int) -> None:
    pcm = np.clip(mix, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype(np.int16)
    # wave module wants interleaved frames
    frames = pcm16.tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(frames)


# --------------------------------------------------------------------------
# Sampled timbres (real instruments; hevi.audio.sampled)
# --------------------------------------------------------------------------


def _resolve_sampled_inst(vd: VoiceDef, global_timbre: str | None) -> str | None:
    """Decide whether a voice renders from the sample library, and with
    which instrument.  Returns the sampled instrument name, or None for
    the synth recipes.  Precedence: voice ``timbre=`` > render-level
    ``timbre`` > ``inst=`` naming a sampled-only instrument."""
    from hevi.audio.sampled import available_instruments, sampled_for_synth_inst

    sampled_names = set(available_instruments())
    mode = vd.timbre or global_timbre or ""
    if mode == "synth":
        return None
    if mode == "sampled":
        if vd.sampled_inst:
            return vd.sampled_inst
        if vd.inst in sampled_names:
            return vd.inst
        return sampled_for_synth_inst(vd.inst)
    # no explicit mode: inst= naming an instrument the synth does not
    # have a recipe for (marimba, vibraphone, ...) selects sampled.
    synth_insts = {"piano", "pluck", "strings", "pad", "bass", "sine", "drums"}
    if vd.inst in sampled_names and vd.inst not in synth_insts:
        return vd.sampled_inst or vd.inst
    if vd.sampled_inst:
        return vd.sampled_inst
    return None


def render_score(
    score: ParsedScore,
    align: dict[str, float] | None = None,
    *,
    seed: int = 42,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timbre: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Render a parsed score. Returns (stereo float mix, sidecar dict).

    ``timbre``: None (default; per-voice attributes decide, synth
    otherwise), ``"synth"`` (force the numpy recipes) or ``"sampled"``
    (force the vendored VCSL sample library wherever a voice maps to
    an instrument; unmapped voices fall back to synth with a warning).
    """
    sr = int(sample_rate)
    tmap = build_time_map(score, align)
    total_s = tmap.time(score.total_beats) + 1.0  # release tail
    if total_s <= 0.05:
        raise ScoreRenderError("rendered duration is zero")
    n = int(total_s * sr) + 1
    mix = np.zeros((n, 2), dtype=np.float64)

    if timbre is not None and timbre not in ("synth", "sampled"):
        raise ScoreRenderError(f"bad timbre: {timbre!r} (synth|sampled)")

    rng_timing = np.random.default_rng(int(seed))
    rng_noise = np.random.default_rng(int(seed) + 12345)

    # Sampled-timbre resolution per voice (None = synth recipes).
    sampled_warnings: list[str] = []
    sampled_by_voice: dict[str, str | None] = {}
    sampled_notes = 0
    synth_fallback_notes = 0
    if timbre == "sampled" or any(
        vd.timbre or vd.sampled_inst for vd in score.voices.values()
    ) or any(vd.inst not in
             {"piano", "pluck", "strings", "pad", "bass", "sine", "drums"}
             for vd in score.voices.values()):
        try:
            for vid, vd in score.voices.items():
                sampled_by_voice[vid] = _resolve_sampled_inst(vd, timbre)
        except Exception as exc:  # library missing/broken: all synth
            sampled_warnings.append(f"sampled timbre unavailable: {exc}")
            sampled_by_voice = {}
    elif timbre == "synth":
        sampled_by_voice = dict.fromkeys(score.voices)
    for vid, inst_name in sorted(sampled_by_voice.items()):
        vd0 = score.voices[vid]
        if vd0.inst == "drums":
            continue  # drum voices map per-hit (DRUM_TO_SAMPLED), see loop
        if (vd0.timbre == "sampled" or timbre == "sampled") and inst_name is None:
            sampled_warnings.append(
                f"voice {vid}: no sampled instrument for inst={vd0.inst!r}; "
                "using synth"
            )
    sampled_used: set[str] = set()

    ordered = sorted(
        (e for e in score.events),
        key=lambda e: (e.start_beat, e.voice, e.midi if e.midi is not None else -1),
    )
    # chord roll offsets: index inside each chord group (ascending midi)
    chord_seen: dict[int, int] = {}

    for ev in ordered:
        if ev.midi is None:
            continue
        vd = score.voices.get(ev.voice, VoiceDef(ev.voice))
        jitter_ms = float(rng_timing.uniform(-6.0, 6.0))
        start_s = tmap.time(ev.start_beat) + jitter_ms / 1000.0
        end_s = tmap.time(ev.start_beat + ev.dur_beats)
        dur_s = max(0.05, end_s - tmap.time(ev.start_beat))
        vel = ev.velocity
        pan = 0.0
        if vd.role == "melody":
            start_s -= 0.008
            vel = min(127, round(vel * 1.12))
        if ev.chord_id >= 0:
            idx = chord_seen.get(ev.chord_id, 0)
            chord_seen[ev.chord_id] = idx + 1
            start_s += idx * 0.012  # micro arpeggio, low note first
        start = int(max(0.0, start_s) * sr)
        gain = (vel / 127.0) * vd.gain
        if vd.inst == "drums":
            name = _GM_DRUMS.get(ev.midi)
            if name is None:
                name = "kick" if ev.midi < 38 else ("snare" if ev.midi < 42 else "hat")
            drum_sampled = sampled_by_voice.get(ev.voice)
            if drum_sampled is None and (
                vd.timbre == "sampled" or timbre == "sampled"
            ):
                from hevi.audio.sampled import DRUM_TO_SAMPLED

                drum_sampled = DRUM_TO_SAMPLED.get(name)
            mono = None
            if drum_sampled:
                try:
                    from hevi.audio.sampled import render_sampled_oneshot

                    mono = render_sampled_oneshot(drum_sampled, vel, sr)
                    sampled_notes += 1
                    sampled_used.add(drum_sampled)
                except Exception as exc:
                    sampled_warnings.append(
                        f"voice {ev.voice}: sampled drum {name} failed "
                        f"({exc}); using synth"
                    )
                    mono = None
            if mono is None:
                if drum_sampled:
                    synth_fallback_notes += 1
                mono = _synth_drum(name, vd.kit, sr, rng_noise, vel)
            _add_stereo(mix, mono, start, 0.0, gain * 0.9)
            continue
        if vd.role in ("melody", "bass") or vd.inst == "bass":
            pan = 0.0
        else:
            pan = float(np.clip((ev.midi - 60) / 60.0, -0.3, 0.3))
        # piano pedal: let the recipe ring, and stretch short notes a bit
        eff_dur = dur_s
        if vd.inst == "piano":
            eff_dur = max(dur_s, min(dur_s + 0.45, score.meter_beats * (60.0 / score.bpm)))
        sampled_inst = sampled_by_voice.get(ev.voice)
        mono = None
        if sampled_inst:
            try:
                from hevi.audio.sampled import render_sampled_note

                mono = render_sampled_note(
                    sampled_inst, ev.midi, eff_dur, vel, sr
                )
                sampled_notes += 1
                sampled_used.add(sampled_inst)
            except Exception as exc:
                sampled_warnings.append(
                    f"voice {ev.voice}: sampled note failed ({exc}); "
                    "using synth"
                )
                mono = None
        if mono is None:
            if sampled_inst:
                synth_fallback_notes += 1
            mono = _synth_note(vd.inst, ev.midi, eff_dur, vel, sr)
        inst_gain = {"piano": 0.34, "pluck": 0.4, "strings": 0.3,
                     "pad": 0.3, "bass": 0.5, "sine": 0.42}.get(vd.inst, 0.36)
        _add_stereo(mix, mono, start, pan, gain * inst_gain)

    for beat in sorted(score.hits):
        start = int(max(0.0, tmap.time(beat)) * sr)
        _add_stereo(mix, _synth_hit(sr, rng_noise), start, 0.0, 0.85)

    # mastering: RMS to target, then peak ceiling
    rms = float(np.sqrt(np.mean(mix**2))) if mix.size else 0.0
    if rms > 1e-9:
        target_rms = 10 ** (TARGET_RMS_DBFS / 20.0)
        mix *= target_rms / rms
    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    ceiling = 10 ** (PEAK_LIMIT_DBFS / 20.0)
    if peak > ceiling:
        mix *= ceiling / peak

    marks_out = [
        {"name": name, "at_s": round(tmap.time(beat), 4)}
        for name, beat in sorted(score.marks.items(), key=lambda kv: kv[1])
    ]
    stretches_out: list[dict[str, Any]] = []
    anchor_times = {name: t for _, t, name in tmap.anchors}
    for st in tmap.stretches:
        t0, t1 = anchor_times[st["from"]], anchor_times[st["to"]]
        i0, i1 = int(t0 * sr), min(n, int(t1 * sr))
        seg_rms_db = -120.0
        if i1 > i0:
            seg = mix[i0:i1]
            seg_rms = float(np.sqrt(np.mean(seg**2)))
            if seg_rms > 1e-12:
                seg_rms_db = round(20 * math.log10(seg_rms), 2)
        stretches_out.append({**st, "rms_db": seg_rms_db})

    voices_out = [
        {
            "id": vid,
            "inst": vd.inst,
            "role": vd.role,
            "gain": vd.gain,
            "note_count": score.note_count(vid),
            "timbre": (
                f"sampled:{sampled_by_voice[vid]}"
                if sampled_by_voice.get(vid)
                else "synth"
            ),
        }
        for vid, vd in sorted(score.voices.items())
        if score.note_count(vid) > 0 or any(
            e.voice == vid for e in score.events
        )
    ]
    warnings = (
        list(score.warnings)
        + list(tmap.warnings)
        + list(dict.fromkeys(sampled_warnings))
    )
    if sampled_notes and synth_fallback_notes:
        engine = "sampled+synth"
    elif sampled_notes:
        engine = "sampled"
    else:
        engine = "numpy_synth"
    sidecar: dict[str, Any] = {
        "title": score.title,
        "voices": voices_out,
        "note_count": score.note_count(),
        "marks": marks_out,
        "stretches": stretches_out,
        "duration_s": round(total_s, 4),
        "seed": int(seed),
        "engine": engine,
        "timbre": timbre,
        "sampled": {
            "instruments": sorted(sampled_used),
            "notes": sampled_notes,
            "synth_fallback_notes": synth_fallback_notes,
        },
        "sample_rate": sr,
        "warnings": warnings,
    }
    return mix, sidecar


# --------------------------------------------------------------------------
# Direction mode: product + scenes -> ABC text
# --------------------------------------------------------------------------

PRODUCT_MAP: dict[str, str] = {
    "devtool": "pulse",
    "ai": "pulse",
    "hardware": "pulse",
    "consumer": "piano",
    "cute": "piano",
    "creative": "cinematic",
    "game": "pulse",
    "data": "lofi",
    "explainer": "piano",
    "calm": "lofi",
    "guofeng": "cinematic",
    "hype": "cinematic",
}

TEMPLATES: dict[str, dict[str, Any]] = {
    "pulse": {
        "bpm": 122, "melody_inst": "pluck", "harmony_inst": "sine",
        "progression": [0, 5, 3, 4], "drums": True,
    },
    "piano": {
        "bpm": 96, "melody_inst": "piano", "harmony_inst": "piano",
        "progression": [0, 3, 5, 4], "drums": False,
    },
    "cinematic": {
        "bpm": 84, "melody_inst": "strings", "harmony_inst": "pad",
        "progression": [0, 5, 3, 6], "drums": True,
    },
    "lofi": {
        "bpm": 76, "melody_inst": "piano", "harmony_inst": "sine",
        "progression": [0, 3, 5, 4], "drums": True,
    },
}

_LETTERS = ["C", "D", "E", "F", "G", "A", "B"]
_KEY_TONICS = ["C", "G", "F", "D"]


def _deg_letter(key_idx: int, degree: int, *, lower: bool = False,
                octave_comma: bool = False) -> str:
    letters = _LETTERS[key_idx:] + _LETTERS[:key_idx]
    letter = letters[degree % 7]
    if lower:
        letter = letter.lower()
    if octave_comma:
        letter += ","
    return letter


def _dyn_token(energy: float) -> str:
    if energy < 0.2:
        return "!pp!"
    if energy < 0.4:
        return "!mp!"
    if energy < 0.65:
        return "!mf!"
    if energy < 0.85:
        return "!f!"
    return "!ff!"


def _dur_suffix(beats: float) -> str:
    if beats == int(beats):
        return str(int(beats)) if beats != 1 else ""
    if beats == 0.5:
        return "/2"
    return f"{beats:g}"


_DRUM_PATTERNS: dict[str, list[tuple[str, float]]] = {
    # (ABC token for a GM drum note, beats) — sequential, each bar sums to 4
    # C,,=kick(36)  D,,=snare(38)  F,,=hat(42)
    "pulse": [("C,,", 1), ("F,,", 0.5), ("F,,", 0.5), ("D,,", 1), ("F,,", 0.5), ("F,,", 0.5)],
    "cinematic": [("C,,", 2), ("F,,", 1), ("D,,", 1)],
    "lofi": [("C,,", 1), ("F,,", 0.5), ("F,,", 0.5), ("D,,", 1), ("F,,", 1)],
    "piano": [("F,,", 1), ("F,,", 1), ("F,,", 1), ("F,,", 1)],
}


def _split_bars(total_beats: int) -> list[int]:
    """Split a beat count into bar sizes of <=4, avoiding 1-beat bars."""
    bars: list[int] = []
    rem = total_beats
    while rem > 0:
        if rem <= 4:
            bars.append(rem)
            break
        if rem - 4 == 1:
            bars.append(3)
            rem -= 3
        else:
            bars.append(4)
            rem -= 4
    return bars


def _rhythm_for(bar_beats: int, energy: float) -> list[float]:
    if energy < 0.3:
        if bar_beats <= 2:
            return [float(bar_beats)]
        return [2.0, float(bar_beats - 2)]
    if energy < 0.7:
        return [1.0] * bar_beats
    if bar_beats == 4:
        return [1.0, 0.5, 0.5, 1.0, 1.0]
    if bar_beats == 3:
        return [0.5, 0.5, 1.0, 1.0]
    if bar_beats == 2:
        return [0.5, 0.5, 1.0]
    return [1.0]


def _fit_pattern(
    pattern: list[tuple[str, float]], bar_beats: float
) -> list[tuple[str, float]]:
    """Truncate/extend a (token, beats) pattern to exactly bar_beats."""
    out: list[tuple[str, float]] = []
    acc = 0.0
    for tok, d in pattern:
        if acc + d <= bar_beats:
            out.append((tok, d))
            acc += d
        else:
            if bar_beats - acc > 0:
                out.append((tok, bar_beats - acc))
            acc = bar_beats
            break
    if acc < bar_beats and out:
        tok, d = out[-1]
        out[-1] = (tok, d + (bar_beats - acc))
    return out


def generate_score(
    product: str,
    scenes: list[dict[str, Any]],
    style: str | None = None,
    *,
    seed: int = 42,
) -> tuple[str, dict[str, float]]:
    """Generate (abc_text, align) from a product category + scene list."""
    if product not in PRODUCT_MAP:
        raise ScoreRenderError(
            f"unknown product {product!r}; known: {sorted(PRODUCT_MAP)}"
        )
    style_name = style or PRODUCT_MAP[product]
    if style_name not in TEMPLATES:
        raise ScoreRenderError(
            f"unknown style {style_name!r}; known: {sorted(TEMPLATES)}"
        )
    if not scenes:
        raise ScoreRenderError("direction mode requires at least one scene")
    prev_end = None
    for sc in scenes:
        if "id" not in sc or "start_s" not in sc or "end_s" not in sc:
            raise ScoreRenderError(f"scene missing id/start_s/end_s: {sc!r}")
        if float(sc["end_s"]) <= float(sc["start_s"]):
            raise ScoreRenderError(f"scene {sc['id']!r}: end_s must exceed start_s")
        if prev_end is not None and float(sc["start_s"]) < prev_end - 1e-9:
            raise ScoreRenderError("scenes must be ordered and non-overlapping")
        prev_end = float(sc["end_s"])

    tpl = TEMPLATES[style_name]
    bpm = int(tpl["bpm"])
    spb = 60.0 / bpm  # seconds per quarter beat
    rng = np.random.default_rng(int(seed))
    key = _KEY_TONICS[int(rng.integers(0, len(_KEY_TONICS)))]
    key_idx = _LETTERS.index(key)
    pentatonic = style_name == "cinematic" and product == "guofeng"
    scale_pool = [0, 1, 2, 4, 5] if pentatonic else [0, 1, 2, 3, 4, 5, 6]
    motif = [int(scale_pool[int(rng.integers(0, len(scale_pool)))]) for _ in range(4)]
    prog: list[int] = tpl["progression"]

    n_scenes = len(scenes)
    drop_idx = n_scenes - 1  # last scene is the drop
    mel_bars: list[str] = []
    har_bars: list[str] = []
    bas_bars: list[str] = []
    drm_bars: list[str] = []
    align: dict[str, float] = {}

    bar_counter = 0
    for si, sc in enumerate(scenes):
        sid = str(sc["id"])
        energy = float(np.clip(float(sc.get("energy", 0.6)), 0.0, 1.0))
        dur_s = float(sc["end_s"]) - float(sc["start_s"])
        # Beat-quantised scene length: segment nominal durations stay
        # within a few percent of the picture, so fitting bends stay small.
        total_beats = max(2, round(dur_s / spb))
        bar_sizes = _split_bars(total_beats)
        align[sid] = float(sc["start_s"])
        dyn = _dyn_token(energy)
        scene_mel: list[str] = []
        scene_har: list[str] = []
        scene_bas: list[str] = []
        scene_drm: list[str] = []
        for bi, bs in enumerate(bar_sizes):
            chord_deg = prog[bar_counter % len(prog)]
            bar_counter += 1
            prefix_m = ""
            if bi == 0:
                prefix_m = f"!mark:{sid}!{dyn}"
                if si == drop_idx and n_scenes >= 2:
                    prefix_m += "!hit!"
            scene_rng = np.random.default_rng(int(seed) * 100003 + si * 131 + bi)
            notes = []
            for mi, r in enumerate(_rhythm_for(bs, energy)):
                deg = motif[mi % len(motif)] + (0 if mi < 4 else 2)
                if energy >= 0.7 and r == 1.0 and scene_rng.random() < 0.35:
                    deg = int(scale_pool[int(scene_rng.integers(0, len(scale_pool)))])
                notes.append(_deg_letter(key_idx, deg, lower=True) + _dur_suffix(r))
            scene_mel.append(prefix_m + " ".join(notes))
            chord = "[" + "".join(
                _deg_letter(key_idx, chord_deg + off) for off in (0, 2, 4)
            ) + "]"
            if style_name == "cinematic" or bs < 2:
                scene_har.append((dyn if bi == 0 else "") + chord + _dur_suffix(bs))
            else:
                half = bs // 2
                scene_har.append(
                    (dyn if bi == 0 else "")
                    + chord + _dur_suffix(bs - half) + " " + chord + _dur_suffix(half)
                )
            root = _deg_letter(key_idx, chord_deg, octave_comma=True)
            fifth = _deg_letter(key_idx, chord_deg + 4, octave_comma=True)
            if style_name == "pulse":
                bas_pat = [(root, 1.0)] * bs
            elif style_name == "cinematic":
                bas_pat = [(root, float(bs))]
            elif style_name == "lofi":
                bas_pat = [(root, 2.0), ("z", 1.0), (fifth, 1.0)]
            else:
                bas_pat = [(root, 2.0), (fifth, 2.0)]
            bas = " ".join(
                tok + _dur_suffix(d) for tok, d in _fit_pattern(bas_pat, float(bs))
            )
            scene_bas.append((dyn if bi == 0 else "") + bas)
            if tpl["drums"] and energy >= 0.25:
                pat = _fit_pattern(_DRUM_PATTERNS[style_name], float(bs))
                scene_drm.append(
                    (dyn if bi == 0 else "")
                    + " ".join(tok + _dur_suffix(d) for tok, d in pat)
                )
            else:
                scene_drm.append("z" + _dur_suffix(bs))
        if si == n_scenes - 2 and n_scenes >= 2 and len(bar_sizes) >= 2:
            # Drop preparation: the scene's final bar becomes a full-bar
            # rest in every voice (inside the scene's own beat budget, so
            # the pause does not distort the fitted tempo).
            rest = "z" + _dur_suffix(bar_sizes[-1])
            scene_mel[-1] = rest
            scene_har[-1] = rest
            scene_bas[-1] = rest
            scene_drm[-1] = rest
        mel_bars.extend(scene_mel)
        har_bars.extend(scene_har)
        bas_bars.extend(scene_bas)
        drm_bars.extend(scene_drm)

    def _join(bars: list[str]) -> str:
        out_lines = [
            " | ".join(bars[i : i + 4]) + " |" for i in range(0, len(bars), 4)
        ]
        return "\n".join(out_lines)

    abc = "\n".join(
        [
            "X:1",
            f"T:Generated {product} ({style_name})",
            "M:4/4",
            "L:1/4",
            f"Q:1/4={bpm}",
            f"K:{key}",
            f"V:1 inst={tpl['melody_inst']} role=melody gain=1.0",
            f"V:2 inst={tpl['harmony_inst']} role=harmony gain=0.8",
            "V:3 inst=bass role=bass gain=0.9",
            "V:4 inst=drums role=drums kit=pop",
            "V:1",
            _join(mel_bars),
            "V:2",
            _join(har_bars),
            "V:3",
            _join(bas_bars),
            "V:4",
            _join(drm_bars),
            "",
        ]
    )
    return abc, align
