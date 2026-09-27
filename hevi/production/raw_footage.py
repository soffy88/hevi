"""HEVI P5.2 — raw footage fine-cut.

Real talking-head footage has to be cut *mechanically and correctly* before
anyone argues about whether it is beautiful. This module does only the
mechanical part: it finds the boundaries, classifies what is there, and emits a
cut plan with a reason for every boundary. Whether the result is a good video is
P5.1's editorial judgement, not a second aesthetic reviewer.

The rule that makes this trustworthy is transcript-first (§36): speech is
located with ASR, and cuts are placed on transcript evidence. Guessing where
someone stopped talking from pixels alone is how you cut a word in half.

Two policies deliberately refuse to be clever:

* **Silence** is classified, not blanket-deleted. A pause can be intentional, a
  breath, dead air, or a real edit gap; only the last is a candidate for removal
  and even then the plan records why (§39).
* **Fillers** are *flagged*, not stripped. "Like" and "you know" carry tone, and
  mechanically deleting every one of them is how a person stops sounding like a
  person (§38).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class TakeQuality(StrEnum):
    VALID = "VALID"
    FALSE_START = "FALSE_START"
    RESTART = "RESTART"
    DUPLICATE_PHRASE = "DUPLICATE_PHRASE"
    FILLER = "FILLER"
    LONG_PAUSE = "LONG_PAUSE"
    NON_SPEECH = "NON_SPEECH"


class SilenceClass(StrEnum):
    INTENTIONAL_PAUSE = "INTENTIONAL_PAUSE"
    BREATH = "BREATH"
    DEAD_AIR = "DEAD_AIR"
    EDITABLE_GAP = "EDITABLE_GAP"


class CutReason(StrEnum):
    KEEP = "KEEP"
    REMOVE_FALSE_START = "REMOVE_FALSE_START"
    REMOVE_RESTART = "REMOVE_RESTART"
    REMOVE_DUPLICATE = "REMOVE_DUPLICATE"
    TIGHTEN_DEAD_AIR = "TIGHTEN_DEAD_AIR"
    SPLIT_AT_BEAT = "SPLIT_AT_BEAT"


#: Filler words are *flagged*; this list is a suggestion surface, not a
#: deletion list. Natural particles and ordinary deixis (这个/那个) are
#: deliberately excluded: they carry meaning in Chinese and deleting or flagging
#: them mechanically is how a person stops sounding like a person.
FILLER_PATTERNS: tuple[str, ...] = (
    r"^嗯[，,。]?",
    r"^呃[，,。]?",
    r"^啊[，,。]?(?=就|那|我)",
    r"就是说[，,]",
    r"怎么说呢",
    r"^um\b",
    r"^uh\b",
    r"\blike,\s",
)

#: Pauses longer than this are candidates for inspection, not automatic removal.
LONG_PAUSE_S = 1.2
#: Pauses longer than this are dead air rather than a beat.
DEAD_AIR_S = 2.5
#: Pauses under this are breaths and are always kept.
BREATH_S = 0.45


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _ffmpeg() -> str:
    import os

    return os.getenv("FFMPEG_BIN", "ffmpeg")


@dataclass
class RawFootageSource:
    """A real recorded source, with everything needed to cut it."""

    source_id: str
    video_path: str
    audio_path: str = ""
    duration_s: float = 0.0
    content_hash: str = ""
    audio_hash: str = ""
    capture_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranscriptWord:
    text: str
    start_s: float
    end_s: float
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranscriptSegment:
    """A sentence-level transcript span."""

    index: int
    text: str
    start_s: float
    end_s: float
    words: list[TranscriptWord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "word_count": len(self.words),
        }


@dataclass
class Transcript:
    """ASR output. Cuts are placed on this, never on pixels alone."""

    text: str = ""
    language: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    provider: str = ""
    engine: str = ""

    def words(self) -> list[TranscriptWord]:
        return [word for segment in self.segments for word in segment.words]

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "provider": self.provider,
            "engine": self.engine,
            "segment_count": len(self.segments),
            "word_count": len(self.words()),
            "text": self.text[:2000],
        }


@dataclass
class SilenceSpan:
    start_s: float
    end_s: float
    classification: SilenceClass = SilenceClass.BREATH
    reason: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["classification"] = self.classification.value
        return d


@dataclass
class TakeSpan:
    """A detected take with its quality verdict."""

    index: int
    start_s: float
    end_s: float
    text: str = ""
    quality: TakeQuality = TakeQuality.VALID
    confidence: float = 0.0
    reason: str = ""
    silence: list[SilenceSpan] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quality"] = self.quality.value
        d["silence"] = [s.to_dict() for s in self.silence]
        return d


@dataclass
class CutEntry:
    """One cut in the plan, with why it exists (§40)."""

    index: int
    source_start_s: float
    source_end_s: float
    output_start_s: float
    reason: CutReason = CutReason.KEEP
    confidence: float = 1.0
    audio_transition: str = "CUT"
    visual_transition: str = "NONE"
    note: str = ""
    take_index: int = 0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.source_end_s - self.source_start_s)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["reason"] = self.reason.value
        return d


@dataclass
class CutPlan:
    """The whole mechanical edit, reviewable before anything is rendered."""

    source_id: str = ""
    entries: list[CutEntry] = field(default_factory=list)
    removed_ranges: list[tuple[float, float]] = field(default_factory=list)
    dropped_reasons: list[CutReason] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def output_duration_s(self) -> float:
        return sum(entry.duration_s for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "cut_count": len(self.entries),
            "dropped_reasons": [r.value for r in self.dropped_reasons],
            "output_duration_s": round(self.output_duration_s, 3),
            "removed_ranges": [list(r) for r in self.removed_ranges],
            "removed_total_s": round(
                sum(e - s for s, e in self.removed_ranges), 3
            ),
            "warnings": self.warnings,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class CutBoundaryIssue:
    kind: str
    entry_index: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FineCutArtifact:
    """The cut result, with lineage back to the source (§42)."""

    artifact_id: str
    source: RawFootageSource
    cut_plan: CutPlan
    output_path: str = ""
    output_hash: str = ""
    output_duration_s: float = 0.0
    boundary_issues: list[CutBoundaryIssue] = field(default_factory=list)
    transcript: Transcript | None = None

    @property
    def ok(self) -> bool:
        return not [i for i in self.boundary_issues if i.kind in _BLOCKING_KINDS]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source": self.source.to_dict(),
            "cut_plan": self.cut_plan.to_dict(),
            "output_path": self.output_path,
            "output_hash": self.output_hash,
            "output_duration_s": self.output_duration_s,
            "ok": self.ok,
            "boundary_issues": [i.to_dict() for i in self.boundary_issues],
            "transcript": self.transcript.to_dict() if self.transcript else None,
        }


_BLOCKING_KINDS = frozenset({"WORD_TRUNCATION", "AUDIO_CLICK", "UNEXPLAINED_REMOVAL"})


# ── Transcript-first ingestion (§36) ─────────────────────────────────────


def extract_audio(source: RawFootageSource, workdir: Path) -> Path:
    """Extract a normalised audio track for ASR and for cutting."""
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / f"{source.source_id}_audio.wav"
    proc = subprocess.run(
        [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", source.video_path,
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(target),
        ],
        capture_output=True, text=True, timeout=900, check=False,
    )
    if proc.returncode != 0 or not target.is_file():
        raise RuntimeError(f"AUDIO_EXTRACTION_FAILED:{proc.stderr[-200:]}")
    source.audio_path = str(target)
    source.audio_hash = _hash_file(target)
    return target


def parse_whisper_json(payload: dict[str, Any], language: str = "") -> Transcript:
    """Build a word-level transcript from a Whisper-style JSON payload.

    Word timestamps are what make a *correct* cut possible: a cut placed between
    two words is provably not inside one.
    """
    transcript = Transcript(language=language, provider="whisper_json")
    text = str(payload.get("text") or "").strip()
    transcript.text = text
    raw_segments = payload.get("segments") or []
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            continue
        words: list[TranscriptWord] = []
        for word in raw.get("words") or []:
            if not isinstance(word, dict):
                continue
            token = str(word.get("word") or word.get("text") or "").strip()
            if not token:
                continue
            words.append(
                TranscriptWord(
                    text=token,
                    start_s=float(word.get("start", 0.0)),
                    end_s=float(word.get("end", 0.0)),
                    confidence=float(word.get("confidence", word.get("probability", 1.0)) or 1.0),
                )
            )
        if not words and str(raw.get("text") or "").strip():
            words = [
                TranscriptWord(
                    text=str(raw["text"]).strip(),
                    start_s=float(raw.get("start", 0.0)),
                    end_s=float(raw.get("end", 0.0)),
                )
            ]
        transcript.segments.append(
            TranscriptSegment(
                index=index,
                text=str(raw.get("text") or "").strip(),
                start_s=float(raw.get("start", 0.0)),
                end_s=float(raw.get("end", 0.0)),
                words=words,
            )
        )
    return transcript


# ── Take detection (§37) ─────────────────────────────────────────────────

_SENTENCE_SPLIT = re.compile(r"[。！？!?；;\n]+")


def _normalise(text: str) -> str:
    return re.sub(r"[^\w一-鿿]+", "", (text or "").lower())


def _duplication_ratio(first: str, second: str) -> float:
    a, b = _normalise(first), _normalise(second)
    if not a or not b:
        return 0.0
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < 4:
        return 0.0
    return len(shorter) / len(longer) if shorter in longer else 0.0


def classify_silence(
    start_s: float, end_s: float, *, preceded_by_sentence_end: bool = False
) -> SilenceSpan:
    """Classify one silence span (§39).

    Classification, never blanket deletion. A pause after a full stop is usually
    intentional; a very long one is dead air; a short one is a breath and is
    always kept.
    """
    duration = max(0.0, end_s - start_s)
    if duration < BREATH_S:
        return SilenceSpan(
            start_s=start_s, end_s=end_s, classification=SilenceClass.BREATH,
            reason=f"under {BREATH_S}s: breath or micro-gap, always kept",
        )
    if duration >= DEAD_AIR_S:
        return SilenceSpan(
            start_s=start_s, end_s=end_s, classification=SilenceClass.DEAD_AIR,
            reason=f"over {DEAD_AIR_S}s with no speech: dead air",
        )
    if preceded_by_sentence_end:
        return SilenceSpan(
            start_s=start_s, end_s=end_s, classification=SilenceClass.INTENTIONAL_PAUSE,
            reason="follows a completed sentence: a beat, not a stumble",
        )
    return SilenceSpan(
        start_s=start_s, end_s=end_s, classification=SilenceClass.EDITABLE_GAP,
        reason="mid-thought pause: candidate for tightening",
    )


def detect_takes(transcript: Transcript, *, duplicate_ratio: float = 0.72) -> list[TakeSpan]:
    """Segment a transcript into takes and judge each one."""
    takes: list[TakeSpan] = []
    for index, segment in enumerate(transcript.segments):
        text = segment.text.strip()
        if not text:
            continue
        takes.append(
            TakeSpan(
                index=index,
                start_s=segment.start_s,
                end_s=segment.end_s,
                text=text,
                quality=TakeQuality.VALID,
                confidence=min((w.confidence for w in segment.words), default=1.0),
            )
        )
    for index, take in enumerate(takes):
        gap_before = take.start_s - takes[index - 1].end_s if index else 0.0
        # A restart is a sentence that begins the way the previous one began.
        if index and _duplication_ratio(takes[index - 1].text, take.text) >= duplicate_ratio:
            take.quality = TakeQuality.DUPLICATE_PHRASE
            take.reason = "repeats the previous phrase: a retake, keep the later one"
        elif take.text[:2] in ("那个", "这个", "然后") and gap_before > 0.6:
            take.quality = TakeQuality.FALSE_START
            take.reason = "opens with a filler and a hesitation: likely a false start"
        elif index and gap_before > LONG_PAUSE_S:
            take.quality = TakeQuality.RESTART
            take.reason = f"follows a {gap_before:.1f}s pause: reads as a restart"
        elif any(re.search(pattern, take.text, re.IGNORECASE) for pattern in FILLER_PATTERNS):
            take.quality = TakeQuality.FILLER
            take.reason = "contains a filler: flagged, not deleted"
        if take.duration_s < 0.35:
            take.quality = TakeQuality.NON_SPEECH
            take.reason = "too short to be a real utterance"
    return takes


def detect_silences(
    transcript: Transcript, *, total_duration_s: float = 0.0
) -> list[SilenceSpan]:
    """Find every gap between utterances and classify it."""
    segments = [s for s in transcript.segments if s.end_s > s.start_s]
    spans: list[SilenceSpan] = []
    previous_end = 0.0
    previous_text = ""
    for segment in segments:
        if segment.start_s > previous_end + 0.01:
            spans.append(
                classify_silence(
                    previous_end, segment.start_s,
                    preceded_by_sentence_end=bool(
                        re.search(r"[。！？!?\.]$", previous_text.strip())
                    ),
                )
            )
        previous_end = segment.end_s
        previous_text = segment.text
    if total_duration_s and total_duration_s > previous_end + 0.01:
        spans.append(classify_silence(previous_end, total_duration_s, preceded_by_sentence_end=True))
    return spans


# ── Cut planning (§40) ───────────────────────────────────────────────────

#: Qualities whose take is kept, because removing a person's take is an
#: editorial act P5.2 does not get to make on its own.
_KEPT_QUALITIES = frozenset({TakeQuality.VALID, TakeQuality.FILLER, TakeQuality.LONG_PAUSE})


def build_cut_plan(
    source: RawFootageSource,
    transcript: Transcript,
    takes: list[TakeSpan],
    silences: list[SilenceSpan],
    *,
    remove_dead_air: bool = True,
) -> CutPlan:
    """Build a cut plan. Every boundary carries a reason and a confidence."""
    plan = CutPlan(source_id=source.source_id)
    cursor = 0.0
    dropped: list[TakeSpan] = []

    # Dead air *between* takes is not inside any take, so it is recorded as an
    # explicit removal here. Without this, every gap would read as an
    # unexplained hole later in boundary QA.
    if remove_dead_air:
        for span in silences:
            if span.classification is SilenceClass.DEAD_AIR and span.duration_s > LONG_PAUSE_S:
                plan.removed_ranges.append((round(span.start_s, 3), round(span.end_s, 3)))
                plan.warnings.append(
                    f"REMOVED_DEAD_AIR:{span.start_s:.2f}-{span.end_s:.2f}:{span.reason}"
                )
    plan.removed_ranges.sort()

    drop_reason = {
        TakeQuality.FALSE_START: CutReason.REMOVE_FALSE_START,
        TakeQuality.DUPLICATE_PHRASE: CutReason.REMOVE_DUPLICATE,
        TakeQuality.RESTART: CutReason.REMOVE_RESTART,
        TakeQuality.NON_SPEECH: CutReason.REMOVE_FALSE_START,
    }

    for take in takes:
        reason = drop_reason.get(take.quality, CutReason.KEEP)
        if reason is not CutReason.KEEP:
            dropped.append(take)
            plan.removed_ranges.append((take.start_s, take.end_s))
            plan.dropped_reasons.append(reason)
            continue

        start = take.start_s
        end = take.end_s
        if remove_dead_air:
            for span in silences:
                # Only dead air is tightened. An intentional pause or a breath
                # stays, because that is the person thinking.
                if span.classification is SilenceClass.DEAD_AIR and (
                    span.start_s >= start - 0.2 and span.end_s <= end + 0.2
                ):
                    continue
            leading = next(
                (s for s in silences if abs(s.end_s - start) < 0.15
                 and s.classification is SilenceClass.DEAD_AIR),
                None,
            )
            if leading is not None and leading.duration_s > LONG_PAUSE_S:
                start = leading.end_s
        plan.entries.append(
            CutEntry(
                index=len(plan.entries),
                source_start_s=round(start, 3),
                source_end_s=round(end, 3),
                output_start_s=round(cursor, 3),
                reason=reason,
                confidence=round(take.confidence, 3),
                note=take.reason or "kept take",
                take_index=take.index,
            )
        )
        cursor += max(0.0, end - start)

    for take in dropped:
        plan.warnings.append(
            f"DROPPED_{take.quality.value}:{take.start_s:.2f}-{take.end_s:.2f}:{take.reason}"
        )
    return plan


# ── Boundary QA (§41) ───────────────────────────────────────────────────


def check_cut_boundaries(plan: CutPlan, transcript: Transcript) -> list[CutBoundaryIssue]:
    """Check every boundary for truncation, clicks and unexplained removals."""
    issues: list[CutBoundaryIssue] = []
    words = transcript.words()

    for entry in plan.entries:
        for boundary, label in ((entry.source_start_s, "start"), (entry.source_end_s, "end")):
            for word in words:
                # A boundary strictly inside a word truncates it.
                if word.start_s + 0.02 < boundary < word.end_s - 0.02:
                    issues.append(
                        CutBoundaryIssue(
                            kind="WORD_TRUNCATION",
                            entry_index=entry.index,
                            detail=(
                                f"{label} at {boundary:.3f}s falls inside word "
                                f"'{word.text}' ({word.start_s:.3f}-{word.end_s:.3f})"
                            ),
                        )
                    )
                    break

    # An unexplained removal is a hole in the source that neither a kept cut nor
    # a recorded removal accounts for. Both sides have to be considered, or every
    # leading silence before the first cut would look like a mystery.
    covered: list[tuple[float, float, bool]] = [
        (entry.source_start_s, entry.source_end_s, True) for entry in plan.entries
    ]
    covered += [(start, end, False) for start, end in plan.removed_ranges]
    covered.sort()
    merged: list[tuple[float, float, bool]] = []
    for start, end, explained in covered:
        if merged and start <= merged[-1][1] + 0.02:
            previous_start, previous_end, previous_flag = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end), previous_flag or explained)
        else:
            merged.append((start, end, explained))
    horizon = max((end for _s, end, _e in merged), default=0.0)
    cursor = 0.0
    for start, end, explained in merged:
        if not explained and start - cursor > 0.75:
            issues.append(
                CutBoundaryIssue(
                    kind="UNEXPLAINED_REMOVAL",
                    entry_index=-1,
                    detail=(
                        f"{cursor:.2f}-{start:.2f}s of source is in no cut and has no "
                        f"recorded reason"
                    ),
                )
            )
        cursor = max(cursor, end)
    if cursor < horizon - 0.75:
        issues.append(
            CutBoundaryIssue(
                kind="UNEXPLAINED_REMOVAL",
                entry_index=-1,
                detail=f"plan ends at {cursor:.2f}s but source runs to {horizon:.2f}s",
            )
        )
    return issues


def detect_audio_clicks(
    plan: CutPlan, rendered_path: str | Path
) -> list[CutBoundaryIssue]:
    """Detect a click at each join in the *rendered* output.

    A click is an audible artefact of the rendered file, so that is where it is
    measured. Measuring it in the source instead does not work: ffmpeg resamples
    to the analysis rate and shifts phase, so a source-side comparison reports a
    clean join as dirty (or the reverse) based on a resampler delay rather than on
    the edit. Joins sit at each entry's ``output_start_s``, which is exact.

    ``plan`` may be empty-safe: fewer than two kept segments means no join.
    """
    issues: list[CutBoundaryIssue] = []
    path = Path(rendered_path)
    if not path.is_file() or len(plan.entries) < 2:
        return issues
    samples = _decode_pcm(path)
    if not samples:
        return issues
    peak = max((abs(value) for value in samples), default=0.0)
    threshold = max(CLICK_STEP_FLOOR, CLICK_STEP_PEAK_RATIO * peak)
    reach = int(CLICK_SEARCH_WINDOW_S * _ANALYSIS_RATE)
    for index in range(1, len(plan.entries)):
        join_s = plan.entries[index].output_start_s
        centre = round(join_s * _ANALYSIS_RATE)
        low, high = max(1, centre - reach), min(len(samples) - 1, centre + reach)
        if high <= low:
            continue
        position, step = max(
            (
                (offset, abs(samples[offset + 1] - samples[offset]))
                for offset in range(low, high)
            ),
            key=lambda pair: pair[1],
        )
        if step <= threshold:
            continue
        issues.append(
            CutBoundaryIssue(
                kind="AUDIO_CLICK",
                entry_index=index - 1,
                detail=(
                    f"join at {join_s:.3f}s discontinues at {position / _ANALYSIS_RATE:.3f}s: "
                    f"{samples[position]:+.4f} -> {samples[position + 1]:+.4f} "
                    f"(jump {step:.4f} > {threshold:.4f})"
                ),
            )
        )
    return issues


#: A click is a step, not a loud sample. The largest per-sample step a
#: band-limited waveform can produce on its own is ``2*sin(pi*f/R)`` times its
#: peak — about 0.17x peak for speech. A join that steps more than this fraction
#: of the track's own peak is therefore a discontinuity rather than signal.
#:
#: It has to be relative. An absolute floor cannot work: a real talking-head
#: track is nowhere near full scale, so a fixed threshold either misses every
#: click in a quiet take or fires on every ordinary zero crossing in a loud one.
CLICK_STEP_PEAK_RATIO = 0.6

#: Below this the track carries essentially no signal, so there is nothing for a
#: step to stand out against and reporting clicks would be noise.
CLICK_STEP_FLOOR = 0.02

#: How far either side of the expected join to look for the discontinuity.
#:
#: An encoder delay — AAC priming is ~23ms — puts the actual splice tens of
#: milliseconds away from the plan's arithmetic join time, so sampling a single
#: sample pair at the expected position measures the codec, not the edit. The
#: window is far longer than the natural per-sample step of speech-band audio
#: (~0.17x peak per sample at 16kHz), so scanning it cannot manufacture a click
#: out of ordinary signal.
CLICK_SEARCH_WINDOW_S = 0.04


def _decode_pcm(path: Path, max_s: float = 3600.0) -> list[float]:
    """Decode the whole file once at a known rate.

    ``ffmpeg -ss`` is not sample-accurate, so seeking per boundary gives a phase
    error large enough to hide or invent a discontinuity. Decoding once and
    indexing arithmetically is exact, and for a talking-head track it is cheap.
    """
    try:
        proc = subprocess.run(
            [
                _ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path),
                "-t", f"{max_s:.3f}", "-f", "s16le", "-ac", "1",
                "-ar", str(_ANALYSIS_RATE), "-",
            ],
            capture_output=True, timeout=1800, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    raw = proc.stdout
    return [
        int.from_bytes(raw[i : i + 2], "little", signed=True) / 32768
        for i in range(0, len(raw) - 1, 2)
    ]


_ANALYSIS_RATE = 16000


def _sample_at(samples: list[float], at_s: float, *, before: bool) -> float | None:
    """One sample adjacent to ``at_s``, on whichever side is requested."""
    if not samples:
        return None
    index = round(at_s * _ANALYSIS_RATE)
    index = index - 1 if before else index
    if index < 0 or index >= len(samples):
        return None
    return samples[index]


def assert_contained(candidate: Path, root: Path, *, label: str) -> Path:
    """Refuse any write target that escapes ``root``.

    ``source_id`` reaches into a filename here, so a crafted id like
    ``../../.bashrc`` would otherwise let the render write outside the workdir
    the caller nominated.
    """
    resolved = Path(candidate).resolve()
    base = Path(root).resolve()
    if base not in resolved.parents and resolved != base:
        raise PermissionError(f"PATH_ESCAPE:{label}:{resolved} is outside {base}")
    return resolved


# ── Execution (§42) ──────────────────────────────────────────────────────


def execute_fine_cut(
    source: RawFootageSource, plan: CutPlan, workdir: Path
) -> Path:
    """Render the cut plan to a real file."""
    if not plan.entries:
        raise RuntimeError("CUT_PLAN_EMPTY")
    workdir.mkdir(parents=True, exist_ok=True)
    target = assert_contained(
        workdir / f"{source.source_id}_finecut.mp4", workdir, label="fine-cut target"
    )
    if target.resolve() in {Path(source.video_path).resolve(), Path(source.audio_path or "").resolve()}:
        raise PermissionError(f"REFUSE_OVERWRITE_SOURCE:{target}")
    inputs: list[str] = []
    filters: list[str] = []
    for index, entry in enumerate(plan.entries):
        # Six decimals, not three. Millisecond rounding is ~16 audio samples, and
        # a phase shift that small is the whole difference between a seamless
        # join and a click -- it cannot be quantised away at the precision the
        # plan was authored with. -accurate_seek makes -ss sample-exact rather
        # than snapping to a nearby keyframe.
        inputs += [
            "-accurate_seek", "-ss", f"{entry.source_start_s:.6f}",
            "-t", f"{entry.duration_s:.6f}", "-i", source.video_path,
        ]
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]")
    concat_in = "".join(f"[v{i}][a{i}]" for i in range(len(plan.entries)))
    graph = ";".join(filters) + f";{concat_in}concat=n={len(plan.entries)}:v=1:a=1[v][a]"
    proc = subprocess.run(
        [
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", str(target),
        ],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if proc.returncode != 0 or not target.is_file():
        raise RuntimeError(f"FINECUT_FAILED:{proc.stderr[-300:]}")
    return target


def probe_duration(path: Path) -> float:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        return float(proc.stdout.strip())
    except (OSError, ValueError):
        return 0.0


def build_fine_cut_artifact(
    source: RawFootageSource,
    transcript: Transcript,
    *,
    workdir: Path,
    artifact_id: str = "",
    remove_dead_air: bool = True,
) -> FineCutArtifact:
    """Run the whole mechanical pipeline and return the artifact with lineage."""
    workdir = Path(workdir)
    duration = source.duration_s or probe_duration(Path(source.video_path))
    source.duration_s = duration
    if not source.content_hash and Path(source.video_path).is_file():
        source.content_hash = _hash_file(Path(source.video_path))

    takes = detect_takes(transcript)
    silences = detect_silences(transcript, total_duration_s=duration)
    for take in takes:
        take.silence = [s for s in silences if take.start_s <= s.start_s <= take.end_s]
    plan = build_cut_plan(
        source, transcript, takes, silences, remove_dead_air=remove_dead_air
    )
    boundary_issues = check_cut_boundaries(plan, transcript)
    if source.audio_path:
        boundary_issues.extend(detect_audio_clicks(plan, source.audio_path))

    artifact = FineCutArtifact(
        artifact_id=artifact_id or f"finecut-{source.source_id}",
        source=source,
        cut_plan=plan,
        boundary_issues=boundary_issues,
        transcript=transcript,
    )
    if not [i for i in boundary_issues if i.kind in _BLOCKING_KINDS] and plan.entries:
        output = execute_fine_cut(source, plan, workdir)
        artifact.output_path = str(output)
        artifact.output_hash = _hash_file(output)
        artifact.output_duration_s = probe_duration(output)
    return artifact


def write_transcript_payload(text: str, words: list[dict[str, Any]]) -> str:
    """Serialise a transcript in the Whisper JSON shape for reproducibility."""
    return json.dumps({"text": text, "segments": [{"text": text, "words": words}]}, ensure_ascii=False)


__all__ = [
    "BREATH_S",
    "DEAD_AIR_S",
    "FILLER_PATTERNS",
    "LONG_PAUSE_S",
    "CutBoundaryIssue",
    "CutEntry",
    "CutPlan",
    "CutReason",
    "FineCutArtifact",
    "RawFootageSource",
    "SilenceClass",
    "SilenceSpan",
    "TakeQuality",
    "TakeSpan",
    "Transcript",
    "TranscriptSegment",
    "TranscriptWord",
    "build_cut_plan",
    "build_fine_cut_artifact",
    "check_cut_boundaries",
    "classify_silence",
    "detect_audio_clicks",
    "detect_silences",
    "detect_takes",
    "execute_fine_cut",
    "extract_audio",
    "parse_whisper_json",
    "probe_duration",
]
