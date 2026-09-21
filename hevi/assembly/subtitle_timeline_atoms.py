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


def normalize_cues(
    cues: Iterable[Any],
    *,
    audio_duration_ms: int,
    unit: str = "ms",
    tolerance_ms: int = 40,
) -> list[CueMs]:
    """Normalize ASR segments/words into deterministic, validated cues.

    ``cues`` may contain ``CueMs``, mappings, or objects with ``start``/``end``
    attributes.  No environment, database, provider, or wall clock is read.
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


def validate_srt(text: str, *, audio_duration_ms: int, tolerance_ms: int = 40) -> list[CueMs]:
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
        parsed, audio_duration_ms=audio_duration_ms, tolerance_ms=tolerance_ms
    )
    if len(normalized) != len(parsed):
        raise ValueError("SRT contains empty cues")
    return normalized


def _parse_srt_match(match: re.Match[str], group: int) -> int:
    clock = match.group(group)
    h, m, s = (int(part) for part in clock.split(":"))
    return (h * 3600 + m * 60 + s) * 1000 + int(match.group(group + 1))


def validate_ass(text: str, *, audio_duration_ms: int, tolerance_ms: int = 40) -> list[CueMs]:
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
    return normalize_cues(parsed, audio_duration_ms=audio_duration_ms, tolerance_ms=tolerance_ms)


def _parse_ass_ts(value: str) -> int:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", value)
    if not match:
        raise ValueError("invalid ASS timestamp syntax")
    return (
        int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
    ) * 1000 + int(match.group(4)) * 10
