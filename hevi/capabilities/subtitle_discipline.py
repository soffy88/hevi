"""Caption discipline (``edit.subtitle_discipline``).

Three rules that used to live only in review notes, now checked by
code before a film ships:

1. Breath breaks. A caption line breaks where a speaker would
   breathe -- at a phrase boundary -- not in the middle of a phrase
   and not wherever a character budget happens to run out. On a
   vertical screen a line holds at most 15 characters.
2. One name, one spelling. A per-project glossary fixes the
   canonical form of every proper name, product name and acronym
   before captions are written; any variant spelling left in the
   captions is a failure, not a style nit.
3. Cut first, transcribe second. Captions for an edited film must
   come from a fresh transcription of the edited audio. Reusing the
   pre-edit timeline after a cut is a stale-timeline failure, even
   if the words look right, because the times are not.

The vertical safe zone belongs here too: on a vertical frame the
caption block's bottom edge must stay at or above 80% of frame
height, clear of the bottom fifth where platform controls sit.

This module does not transcribe audio and does not fix
mis-recognised words by itself -- that still needs a transcript
and, where needed, a human pass. It checks line shape, glossary
use, ordering, timing bounds and timeline freshness, and it can
re-flow an existing caption file through the glossary and the
breath-break rule without touching its timestamps.

Failure contract: empty events, a missing glossary term, an event
with end before start, out-of-order or overlapping events, or an
event past the declared duration all raise CapabilityError. Rule
violations that are a matter of the captions themselves (a line
too long, a variant spelling, a stale timeline source, a
pictograph) are reported as failures in the report, not raised,
so the gate can list them all at once.
"""

from __future__ import annotations

import json
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

VERTICAL_MAX_CHARS_PER_LINE = 15
VERTICAL_SAFE_BOTTOM = 0.80
# Phrase boundaries: a breath lands after one of these, or at a
# space between English words. Splitting anywhere else splits a
# phrase and is only allowed when a single phrase is longer than
# the line budget, in which case the split is flagged.
_BREAK_AFTER = "，。、；：！？,.!?;:\n"
_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"
    "\U00002600-\U000027bf"
    "\U0001f1e6-\U0001f1ff"
    "\uFE0F"
    "]"
)
_FRESH_SOURCES = {"post_edit_retranscription", "post_edit_transcript", "fresh_transcription"}


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def apply_glossary(text: str, glossary: dict[str, list[str]]) -> tuple[str, list[str]]:
    """Replace every variant spelling with its canonical form.

    ``glossary`` maps canonical form -> variant spellings. Longest
    variants go first so a longer variant is never half-replaced by
    a shorter one inside it. Returns the new text and the list of
    variants that were actually replaced.
    """
    if not isinstance(glossary, dict):
        raise CapabilityError("edit.subtitle_discipline: glossary must be an object")
    out = text
    replaced: list[str] = []
    pairs: list[tuple[str, str]] = []
    for canonical, variants in glossary.items():
        if not isinstance(canonical, str) or not canonical:
            raise CapabilityError("edit.subtitle_discipline: glossary canonical form must be non-empty")
        if not isinstance(variants, list):
            raise CapabilityError("edit.subtitle_discipline: glossary variants must be a list")
        for variant in variants:
            if not isinstance(variant, str) or not variant or variant == canonical:
                continue
            pairs.append((variant, canonical))
    for variant, canonical in sorted(pairs, key=lambda p: -len(p[0])):
        if variant in out:
            out = out.replace(variant, canonical)
            replaced.append(variant)
    return out, replaced


def find_glossary_violations(text: str, glossary: dict[str, list[str]]) -> list[str]:
    """Variant spellings still present in ``text``."""
    found: list[str] = []
    for canonical, variants in (glossary or {}).items():
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if isinstance(variant, str) and variant and variant != canonical and variant in text:
                found.append(variant)
    return sorted(set(found))


def split_breath_units(text: str) -> list[str]:
    """Split text into breath units without breaking a phrase.

    Units end after a breath punctuation mark, or at a space between
    English words (the space itself is dropped). A unit is the
    smallest piece a line break may fall after.
    """
    units: list[str] = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                units.append(buf)
                buf = ""
            continue
        buf += ch
        if ch in _BREAK_AFTER:
            units.append(buf)
            buf = ""
    if buf:
        units.append(buf)
    return [u for u in units if u]


def break_lines(text: str, max_chars_per_line: int = VERTICAL_MAX_CHARS_PER_LINE) -> dict[str, Any]:
    """Pack breath units into lines within the character budget.

    Units are never split unless a single unit is longer than the
    budget; that forced split is flagged in ``forced_splits`` so the
    caller can see exactly where a phrase had to be broken.
    """
    if not isinstance(max_chars_per_line, int) or max_chars_per_line <= 0:
        raise CapabilityError("edit.subtitle_discipline: max_chars_per_line must be a positive integer")
    lines: list[str] = []
    forced_splits: list[str] = []
    current = ""
    for unit in split_breath_units(text):
        if len(unit) > max_chars_per_line:
            if current:
                lines.append(current)
                current = ""
            for i in range(0, len(unit), max_chars_per_line):
                chunk = unit[i:i + max_chars_per_line]
                lines.append(chunk)
                forced_splits.append(chunk)
            continue
        if current and len(current) + len(unit) > max_chars_per_line:
            lines.append(current)
            current = unit
        else:
            current += unit
    if current:
        lines.append(current)
    return {"lines": lines, "forced_splits": forced_splits}


def reflow_event_text(text: str, glossary: dict[str, list[str]] | None,
                      max_chars_per_line: int = VERTICAL_MAX_CHARS_PER_LINE) -> dict[str, Any]:
    """Glossary + breath-break re-flow of one caption event's text."""
    clean, replaced = apply_glossary(text, glossary or {})
    broken = break_lines(clean, max_chars_per_line)
    return {
        "original": text,
        "glossaried": clean,
        "glossary_replaced": replaced,
        "lines": broken["lines"],
        "forced_splits": broken["forced_splits"],
    }


def validate_events(
    events: list[dict[str, Any]],
    *,
    max_chars_per_line: int = VERTICAL_MAX_CHARS_PER_LINE,
    duration_sec: float | None = None,
    transcript_source: str = "",
    glossary: dict[str, list[str]] | None = None,
    orientation: str = "vertical",
    subtitle_bottom_fraction: float | None = None,
) -> dict[str, Any]:
    """Validate a caption event list and return the gate report."""
    if not isinstance(events, list) or not events:
        raise CapabilityError("edit.subtitle_discipline: events must be a non-empty list")
    glossary = glossary or {}
    failures: list[dict[str, Any]] = []
    reflowed: list[dict[str, Any]] = []
    prev_end = -1.0
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise CapabilityError(f"edit.subtitle_discipline: event {i} must be an object")
        start, end = ev.get("start_sec"), ev.get("end_sec")
        if not _is_num(start) or not _is_num(end):
            raise CapabilityError(f"edit.subtitle_discipline: event {i} needs numeric start_sec/end_sec")
        start, end = float(start), float(end)
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.subtitle_discipline: event {i} has an invalid time range")
        if start < prev_end - 1e-3:
            raise CapabilityError(f"edit.subtitle_discipline: event {i} overlaps or precedes the previous event")
        prev_end = end
        if duration_sec is not None and end > float(duration_sec) + 1e-3:
            raise CapabilityError(f"edit.subtitle_discipline: event {i} ends past duration_sec")
        text = ev.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise CapabilityError(f"edit.subtitle_discipline: event {i} needs non-empty text")
        flow = reflow_event_text(text, glossary, max_chars_per_line)
        reflowed.append({"index": i, "start_sec": start, "end_sec": end, **flow})
        for line in flow["lines"]:
            if len(line) > max_chars_per_line:
                failures.append({"event": i, "kind": "line_too_long",
                                 "detail": f"line {line!r} is {len(line)} chars, budget {max_chars_per_line}"})
        if flow["forced_splits"]:
            failures.append({"event": i, "kind": "phrase_split_forced",
                             "detail": f"single phrase longer than budget, split at {flow['forced_splits']}"})
        # The delivered captions themselves must already use the
        # canonical spelling. Re-flow can fix a draft, but a draft
        # variant does not pass the gate just because a fix exists.
        variants = find_glossary_violations(text, glossary)
        if variants:
            failures.append({"event": i, "kind": "glossary_variant",
                             "detail": f"variant spellings present, canonical required: {variants}"})
        emoji = sorted(set(_EMOJI_RE.findall(text)))
        if emoji:
            failures.append({"event": i, "kind": "emoji_in_caption",
                             "detail": f"pictographs found: {emoji}"})
    if transcript_source and transcript_source not in _FRESH_SOURCES:
        failures.append({"event": None, "kind": "stale_timeline",
                         "detail": f"transcript_source {transcript_source!r} is not a "
                         "post-edit retranscription; captions for an edited film "
                         "must be re-transcribed from the edited audio"})
    if orientation == "vertical":
        if subtitle_bottom_fraction is not None:
            if float(subtitle_bottom_fraction) > VERTICAL_SAFE_BOTTOM:
                failures.append({"event": None, "kind": "vertical_safe_zone",
                                 "detail": f"caption bottom at {float(subtitle_bottom_fraction):.2f}, "
                                 f"vertical films require at most {VERTICAL_SAFE_BOTTOM}"})
        else:
            failures.append({"event": None, "kind": "vertical_safe_zone_unknown",
                             "detail": "no subtitle_bottom_fraction supplied; safe zone could not be checked"})
    return {
        "capability": "edit.subtitle_discipline",
        "event_count": len(events),
        "max_chars_per_line": max_chars_per_line,
        "orientation": orientation,
        "transcript_source": transcript_source,
        "failures": failures,
        "verdict": "fail" if failures else "pass",
        "reflowed": reflowed,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = params.get("events")
    if not isinstance(events, list):
        raise CapabilityError("edit.subtitle_discipline: events must be a list")
    kwargs: dict[str, Any] = {}
    if params.get("max_chars_per_line") is not None:
        kwargs["max_chars_per_line"] = int(params["max_chars_per_line"])
    if params.get("duration_sec") is not None:
        kwargs["duration_sec"] = float(params["duration_sec"])
    if params.get("transcript_source"):
        kwargs["transcript_source"] = str(params["transcript_source"])
    if params.get("glossary") is not None:
        kwargs["glossary"] = dict(params["glossary"])
    if params.get("orientation"):
        kwargs["orientation"] = str(params["orientation"])
    if params.get("subtitle_bottom_fraction") is not None:
        kwargs["subtitle_bottom_fraction"] = float(params["subtitle_bottom_fraction"])
    report = validate_events(events, **kwargs)
    report_path = out_dir / "subtitle_discipline_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "failures": report["failures"]},
    )


def register_subtitle_discipline_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.subtitle_discipline",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "events": {"type": "array", "items": {"type": "object"}},
                    "max_chars_per_line": {"type": "integer", "exclusiveMinimum": 0},
                    "duration_sec": {"type": "number", "exclusiveMinimum": 0},
                    "transcript_source": {"type": "string"},
                    "glossary": {"type": "object"},
                    "orientation": {"type": "string", "enum": ["vertical", "horizontal"]},
                    "subtitle_bottom_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["events"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Caption discipline gate: breath-break line packing "
                "(vertical at most 15 characters per line, phrases "
                "never split except when a single phrase exceeds the "
                "budget), per-project glossary unification, "
                "post-edit retranscription freshness, pictograph ban, "
                "and vertical caption safe zone."
            ),
            line="edit",
        )
    )
    return ["edit.subtitle_discipline"]


register_subtitle_discipline_capabilities_once()
