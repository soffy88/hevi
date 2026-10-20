"""Deterministic subtitle/timeline atoms.

This module is intentionally provider-free and state-free.  The production
workflow composes these atoms with the existing ``hevi.assembly.assembler``;
it is not a second timeline engine.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any


@dataclass(frozen=True, slots=True)
class CueMs:
    """Canonical subtitle cue.  All public clock values are milliseconds."""

    start_ms: int
    end_ms: int
    text: str
    emotion: str = "neutral"


_SRT_TS = re.compile(r"^(\d{2,}:\d{2}:\d{2})[,\.](\d{3})$")
_SRT_LINE = re.compile(
    r"^(\d{2,}:\d{2}:\d{2})[,\.](\d{3})\s+-->\s+"
    r"(\d{2,}:\d{2}:\d{2})[,\.](\d{3})$"
)


def _int_ms(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("timestamp must be numeric")
    return round(float(value))


def _clock_ms(value: Any, *, unit: str = "ms") -> int:
    """Convert an explicit timestamp to the canonical millisecond clock."""

    if unit == "ms":
        return _int_ms(value)
    if unit == "s":
        return _int_ms(float(value) * 1000.0)
    raise ValueError(f"unsupported timestamp unit: {unit}")


# --- Subtitle QA checks (W3): readability (CPS / min duration) + no-spoiler --
#
# These are pure, provider-free validators.  They never mutate cues and they
# are opt-in for the strict path: ``normalize_cues`` / ``validate_srt`` keep
# their historical behaviour unless ``strict_readability=True`` is passed.

# Unicode ranges counted as "one character = one reading unit" (CJK ideographs,
# Japanese kana, Korean hangul syllables).
_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7AF),
)


def _is_cjk_char(char: str) -> bool:
    code = ord(char)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def _cue_interval_s(raw: Any) -> tuple[float, float, str]:
    """Best-effort (start_s, end_s, text) for CueMs / mapping / object cues.

    ``*_ms`` fields are milliseconds; bare ``start``/``end`` fields are
    seconds (matching ``hevi.assembly.subtitle_align.Cue``).
    """
    if isinstance(raw, CueMs):
        return raw.start_ms / 1000.0, raw.end_ms / 1000.0, str(raw.text)
    if isinstance(raw, dict):
        start_raw = raw.get("start_ms")
        end_raw = raw.get("end_ms")
        if start_raw is not None and end_raw is not None:
            return float(start_raw) / 1000.0, float(end_raw) / 1000.0, str(
                raw.get("text", "") or ""
            )
        return (
            float(raw.get("start", 0) or 0),
            float(raw.get("end", 0) or 0),
            str(raw.get("text", "") or ""),
        )
    start_raw = getattr(raw, "start_ms", None)
    end_raw = getattr(raw, "end_ms", None)
    text = str(getattr(raw, "text", "") or "")
    if start_raw is not None and end_raw is not None:
        return float(start_raw) / 1000.0, float(end_raw) / 1000.0, text
    return float(getattr(raw, "start", 0) or 0), float(getattr(raw, "end", 0) or 0), text


def _readability_counts(text: str) -> tuple[int, int]:
    """Return (cjk_chars, latin_chars); spaces/punctuation/symbols excluded."""
    cjk = latin = 0
    for char in text:
        if _is_cjk_char(char):
            cjk += 1
        elif char.isalnum():
            latin += 1
    return cjk, latin


def validate_cue_readability(
    cues: Iterable[Any],
    *,
    max_cps: float = 15.0,
    max_cps_latin: float = 20.0,
    min_dur_s: float = 0.8,
) -> list[dict[str, Any]]:
    """Check that viewers can actually read each cue in its display time.

    Threshold basis (documented, deliberately conservative hard limits):

    * CJK: adult comfortable reading is roughly <=12 chars/s; the default
      ``max_cps=15.0`` is a *hard* ceiling, not a comfort target -- callers
      aiming for comfortable pacing should pass ``max_cps=12.0``.
    * Latin/other alphanumeric text: ``max_cps_latin=20.0`` chars/s, the
      widely used adult timed-text guideline (e.g. Netflix-style 20 cps).
    * ``min_dur_s=0.8``: below ~0.8 s a cue barely registers at all, no
      matter how short it is (common minimum display time is ~5/6 s).

    Mixed-script cues are judged by the time the text *needs*:
    ``cjk / max_cps + latin / max_cps_latin`` must fit in the cue duration,
    so a mixed cue cannot sneak past by splitting its load across scripts.

    Returns a list of violation dicts (empty = pass).  Pure function: it
    never raises for bad cues and never mutates its input; it only raises
    ``ValueError`` for non-positive limits.  Violation ``kind`` is one of
    ``"duration_too_short"``, ``"cps_exceeded"``, ``"non_positive_duration"``.
    """
    if max_cps <= 0 or max_cps_latin <= 0:
        raise ValueError("max_cps / max_cps_latin must be positive")
    if min_dur_s < 0:
        raise ValueError("min_dur_s must be non-negative")
    violations: list[dict[str, Any]] = []
    for index, raw in enumerate(cues):
        start_s, end_s, text = _cue_interval_s(raw)
        duration_s = end_s - start_s
        base: dict[str, Any] = {
            "index": index,
            "text": text,
            "start_ms": round(start_s * 1000),
            "end_ms": round(end_s * 1000),
            "duration_s": round(duration_s, 4),
        }
        if duration_s <= 0:
            violations.append(
                {
                    **base,
                    "kind": "non_positive_duration",
                    "message": f"cue {index} has non-positive duration {duration_s:.3f}s",
                }
            )
            continue
        if duration_s < min_dur_s:
            violations.append(
                {
                    **base,
                    "kind": "duration_too_short",
                    "min_dur_s": min_dur_s,
                    "message": (
                        f"cue {index} displays {duration_s:.3f}s < minimum {min_dur_s:.3f}s"
                    ),
                }
            )
        cjk_chars, latin_chars = _readability_counts(text)
        required_s = cjk_chars / max_cps + latin_chars / max_cps_latin
        if required_s > duration_s + 1e-9:
            violations.append(
                {
                    **base,
                    "kind": "cps_exceeded",
                    "cjk_chars": cjk_chars,
                    "latin_chars": latin_chars,
                    "cps_cjk": round(cjk_chars / duration_s, 4),
                    "cps_latin": round(latin_chars / duration_s, 4),
                    "max_cps": max_cps,
                    "max_cps_latin": max_cps_latin,
                    "required_duration_s": round(required_s, 4),
                    "message": (
                        f"cue {index} needs {required_s:.2f}s to read "
                        f"({cjk_chars} CJK + {latin_chars} latin chars) "
                        f"but displays {duration_s:.2f}s"
                    ),
                }
            )
    return violations


def _word_stream(words: Iterable[Any]) -> tuple[str, list[float], list[str]]:
    """Flatten a word stream to (char_string, char_start_s, char_word_text).

    Only alphanumeric characters survive (lowercased), so punctuation and
    spacing differences between cues and the word stream cannot break the
    match.  Word times follow the same convention as cues: ``start_ms``
    wins, otherwise ``start`` is seconds.  Words without any timestamp are
    skipped -- the checker never invents a time it was not given.
    """
    chars: list[str] = []
    starts: list[float] = []
    owners: list[str] = []
    for raw in words or ():
        if isinstance(raw, dict):
            text = str(raw.get("word", raw.get("text", "")) or "")
            start_raw = raw.get("start_ms")
            start_s = (
                float(start_raw) / 1000.0
                if start_raw is not None
                else (float(raw["start"]) if raw.get("start") is not None else None)
            )
        else:
            text = str(getattr(raw, "word", getattr(raw, "text", "")) or "")
            start_ms = getattr(raw, "start_ms", None)
            start_s = (
                float(start_ms) / 1000.0
                if start_ms is not None
                else (float(raw.start) if getattr(raw, "start", None) is not None else None)
            )
        if start_s is None:
            continue
        for char in text:
            if char.isalnum():
                chars.append(char.lower())
                starts.append(start_s)
                owners.append(text)
    return "".join(chars), starts, owners


def check_cue_early_start(
    cues: Iterable[Any],
    words: Iterable[Any],
    *,
    tolerance_s: float = 0.05,
) -> list[dict[str, Any]]:
    """Assert no cue appears before its first word is actually spoken.

    Showing a cue early spoils the line (and desyncs karaoke-style burns):
    generation constructs ``cue.start == first word start``, this is the
    missing validator for that invariant.

    Matching strategy (conservative, no false positives by design):

    * Both cue text and the word stream are normalized to alphanumeric-only,
      lowercased character sequences (see ``_word_stream``).
    * Cues are matched *sequentially*: each cue's character sequence is
      searched in the word stream starting at the end of the previous cue's
      match, so word ranges are never reused across cues and a cue is always
      compared with *its own* first word, not an identical earlier word.
    * A cue whose text cannot be found in the remaining word stream is
      skipped silently -- unmatched means "cannot judge", never a violation.

    A violation is reported when ``cue.start < first_word.start - tolerance_s``
    (default tolerance 50 ms absorbs frame/ASR jitter).  Returns violation
    dicts with ``kind == "early_start"``; empty list = pass.
    """
    if tolerance_s < 0:
        raise ValueError("tolerance_s must be non-negative")
    stream, starts, owners = _word_stream(words)
    violations: list[dict[str, Any]] = []
    pointer = 0
    for index, raw in enumerate(cues):
        start_s, _end_s, text = _cue_interval_s(raw)
        needle = "".join(char.lower() for char in text if char.isalnum())
        if not needle:
            continue
        found = stream.find(needle, pointer)
        if found < 0:
            continue
        first_word_start_s = starts[found]
        pointer = found + len(needle)
        if start_s < first_word_start_s - tolerance_s:
            violations.append(
                {
                    "index": index,
                    "kind": "early_start",
                    "text": text,
                    "cue_start_s": round(start_s, 4),
                    "first_word": owners[found],
                    "first_word_start_s": round(first_word_start_s, 4),
                    "early_by_s": round(first_word_start_s - start_s, 4),
                    "tolerance_s": tolerance_s,
                    "message": (
                        f"cue {index} starts {first_word_start_s - start_s:.3f}s "
                        f"before its first word {owners[found]!r} "
                        f"({first_word_start_s:.3f}s)"
                    ),
                }
            )
    return violations


def normalize_cues(
    cues: Iterable[Any],
    *,
    audio_duration_ms: int,
    unit: str = "ms",
    tolerance_ms: int = 40,
    strict_readability: bool = False,
    max_cps: float = 15.0,
    max_cps_latin: float = 20.0,
    min_dur_s: float = 0.8,
) -> list[CueMs]:
    """Normalize ASR segments/words into deterministic, validated cues.

    ``cues`` may contain ``CueMs``, mappings, or objects with ``start``/``end``
    attributes.  No environment, database, provider, or wall clock is read.

    Readability (CPS / minimum duration, see ``validate_cue_readability``)
    is *not* enforced by default, preserving historical behaviour; callers
    that only want the violations should call ``validate_cue_readability``
    directly.  With ``strict_readability=True`` any readability violation
    raises ``ValueError`` instead of returning the cues.
    """

    duration = _int_ms(audio_duration_ms)
    if duration <= 0:
        raise ValueError("audio_duration_ms must be positive")
    result: list[CueMs] = []
    previous = 0
    for raw in cues:
        if isinstance(raw, CueMs):
            start, end, text, emotion = raw.start_ms, raw.end_ms, raw.text, raw.emotion
        else:
            if isinstance(raw, dict):
                start_raw = raw.get("start_ms")
                end_raw = raw.get("end_ms")
                if start_raw is None:
                    start_raw = raw.get("start")
                if end_raw is None:
                    end_raw = raw.get("end")
                text = str(raw.get("text", "") or "").strip()
                emotion = str(raw.get("emotion", "neutral") or "neutral")
            else:
                start_raw = getattr(raw, "start_ms", None)
                end_raw = getattr(raw, "end_ms", None)
                if start_raw is None:
                    start_raw = getattr(raw, "start", None)
                if end_raw is None:
                    end_raw = getattr(raw, "end", None)
                text = str(getattr(raw, "text", "") or "").strip()
                emotion = str(getattr(raw, "emotion", "neutral") or "neutral")
            if start_raw is None or end_raw is None:
                raise ValueError("cue requires start/end or start_ms/end_ms")
            start = _clock_ms(start_raw, unit=unit)
            end = _clock_ms(end_raw, unit=unit)
        text = str(text).strip()
        if not text:
            continue
        if start < 0 or end < start:
            raise ValueError(f"invalid cue interval: {start}..{end}")
        if start < previous:
            raise ValueError("cue timestamps are not monotonic")
        if end > duration + tolerance_ms:
            raise ValueError(f"cue exceeds audio duration: {end}>{duration}+{tolerance_ms}")
        end = min(end, duration)
        if end < start:
            raise ValueError("cue end becomes earlier than start after clamping")
        result.append(CueMs(start, end, text, emotion))
        previous = end
    if strict_readability:
        violations = validate_cue_readability(
            result, max_cps=max_cps, max_cps_latin=max_cps_latin, min_dur_s=min_dur_s
        )
        if violations:
            raise ValueError(f"cue readability violations: {violations}")
    return result


def align_cues(
    cues: Iterable[Any],
    *,
    audio_duration_ms: int,
    fps: int,
    shot_boundaries_ms: Iterable[int] | None = None,
    unit: str = "ms",
) -> list[CueMs]:
    """Canonical deterministic cue alignment; optional shot boundaries are hints."""

    if fps <= 0:
        raise ValueError("fps must be positive")
    normalized = normalize_cues(cues, audio_duration_ms=audio_duration_ms, unit=unit)
    boundaries = sorted({_int_ms(value) for value in (shot_boundaries_ms or ())})
    if not boundaries:
        return normalized
    # Boundaries never move the ASR clock.  They only split a cue at an exact
    # boundary, preserving text and deterministic ordering.
    out: list[CueMs] = []
    for cue in normalized:
        cuts = [b for b in boundaries if cue.start_ms < b < cue.end_ms]
        points = [cue.start_ms, *cuts, cue.end_ms]
        for start, end in pairwise(points):
            out.append(CueMs(start, end, cue.text, cue.emotion))
    return out


def _srt_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


def cues_to_srt(cues: Iterable[CueMs]) -> str:
    blocks = []
    for index, cue in enumerate(cues, 1):
        blocks.append(f"{index}\n{_srt_ts(cue.start_ms)} --> {_srt_ts(cue.end_ms)}\n{cue.text}\n")
    return "\n".join(blocks)


def _ass_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{milli // 10:02d}"


def _ass_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def cues_to_ass(
    cues: Iterable[CueMs],
    *,
    width: int = 1920,
    height: int = 1080,
    font_name: str = "Noto Sans CJK SC",
    font_size: int = 48,
    margin_l: int = 96,
    margin_r: int = 96,
    margin_v: int = 72,
) -> str:
    if min(width, height, font_size, margin_l, margin_r, margin_v) <= 0:
        raise ValueError("ASS dimensions, font size, and safe margins must be positive")
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,{margin_l},{margin_r},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = [
        f"Dialogue: 0,{_ass_ts(cue.start_ms)},{_ass_ts(cue.end_ms)},Default,,,,,,{_ass_text(cue.text)}"
        for cue in cues
    ]
    return "\n".join(header + events) + "\n"


def validate_srt(
    text: str,
    *,
    audio_duration_ms: int,
    tolerance_ms: int = 40,
    strict_readability: bool = False,
    max_cps: float = 15.0,
    max_cps_latin: float = 20.0,
    min_dur_s: float = 0.8,
) -> list[CueMs]:
    blocks = [block for block in text.replace("\r\n", "\n").strip().split("\n\n") if block.strip()]
    parsed: list[CueMs] = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError("invalid SRT block")
        match = _SRT_LINE.match(lines[1].strip())
        if not match:
            raise ValueError("invalid SRT timestamp syntax")
        start = _parse_srt_match(match, 1)
        end = _parse_srt_match(match, 3)
        parsed.append(CueMs(start, end, "\n".join(lines[2:])))
    normalized = normalize_cues(
        parsed,
        audio_duration_ms=audio_duration_ms,
        tolerance_ms=tolerance_ms,
        strict_readability=strict_readability,
        max_cps=max_cps,
        max_cps_latin=max_cps_latin,
        min_dur_s=min_dur_s,
    )
    if len(normalized) != len(parsed):
        raise ValueError("SRT contains empty cues")
    return normalized


def _parse_srt_match(match: re.Match[str], group: int) -> int:
    clock = match.group(group)
    h, m, s = (int(part) for part in clock.split(":"))
    return (h * 3600 + m * 60 + s) * 1000 + int(match.group(group + 1))


def validate_ass(
    text: str,
    *,
    audio_duration_ms: int,
    tolerance_ms: int = 40,
    strict_readability: bool = False,
    max_cps: float = 15.0,
    max_cps_latin: float = 20.0,
    min_dur_s: float = 0.8,
) -> list[CueMs]:
    parsed: list[CueMs] = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10:
            raise ValueError("invalid ASS dialogue")
        start, end = (_parse_ass_ts(fields[i].strip()) for i in (1, 2))
        parsed.append(CueMs(start, end, fields[9].replace(r"\N", "\n")))
    if not parsed:
        raise ValueError("ASS contains no dialogue")
    return normalize_cues(
        parsed,
        audio_duration_ms=audio_duration_ms,
        tolerance_ms=tolerance_ms,
        strict_readability=strict_readability,
        max_cps=max_cps,
        max_cps_latin=max_cps_latin,
        min_dur_s=min_dur_s,
    )


def _parse_ass_ts(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", value)
    if not match:
        raise ValueError("invalid ASS timestamp syntax")
    return (
        int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
    ) * 1000 + int(match.group(4)) * 10
