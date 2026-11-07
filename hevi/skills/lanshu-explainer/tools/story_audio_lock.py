#!/usr/bin/env python3
# MIT License. Part of hevi skill lanshu-explainer.
# Implements the story.json contract of cclank/lanshu-create-ai-presenter-video
# (https://github.com/cclank/lanshu-create-ai-presenter-video, MIT,
# explainer/tools/story.py, commit 762d3ee, 2026-10-20).
"""Audio-locked timeline: build and validate a lanshu-compatible story.json.

The narration is the master clock. Word timings come from hevi's
``audio.forced_align`` capability (measured, is_estimated=False) or from a TTS
engine's native word boundaries, and are assembled here into the story.json
contract that the twelve explainer style kits consume:

    lines[i] = {"i", "text", "start", "end", "words": [[word, t_seconds], ...], "chapter"}
    chapters = [{"n", "key", "title", "start", "end"}, ...]
    + "end" (closing line), "recap" (one-frame recap), "notes" (storyboard notes, unvoiced)

See hevi skill lanshu-explainer (SKILL.md) for the workflow.
"""

from __future__ import annotations

from typing import Any, Optional

OVERLAP_TOLERANCE_S = 0.01


def story_from_word_timings(
    title: str,
    chapters: list[dict[str, Any]],
    word_timings: list[dict[str, Any]],
    *,
    subtitle: str = "",
    voice: str = "hevi tts",
    end_line: Optional[dict[str, Any]] = None,
    recap: Optional[dict[str, Any]] = None,
    notes: Optional[dict[str, list[str]]] = None,
) -> dict[str, Any]:
    """Assemble a story.json from chapter scripts and measured word timings.

    ``chapters``: [{"key", "title", "lines": [text, ...]}, ...] in spoken order.
    ``word_timings``: [{"word", "start_ms", "end_ms"}, ...] in spoken order, the
    concatenation of every narration line (matches ``audio.forced_align`` output).

    Word counts must match the script exactly: every timing must equal the
    concatenation of the spoken unit of its line's text. Because Chinese has no
    spaces, callers pass one timing per character/punctuation, in text order.
    """
    total_units = sum(len(line) for chapter in chapters for line in chapter["lines"])
    if len(word_timings) != total_units:
        raise ValueError(
            f"word_timings has {len(word_timings)} entries but the script has "
            f"{total_units} characters/units"
        )
    cursor = 0
    lines: list[dict[str, Any]] = []
    chapter_spans: list[dict[str, Any]] = []
    idx = 1
    for n, chapter in enumerate(chapters, start=1):
        first_idx = cursor
        for text in chapter["lines"]:
            chunk = word_timings[cursor:cursor + len(text)]
            if "".join(t["word"] for t in chunk) != text:
                raise ValueError(
                    f"word timings do not match line text at line {idx}: "
                    f"expected {text!r}, got {''.join(t['word'] for t in chunk)!r}"
                )
            words = [[t["word"], t["start_ms"] / 1000.0] for t in chunk]
            line = {
                "i": idx,
                "text": text,
                "start": chunk[0]["start_ms"] / 1000.0,
                "end": chunk[-1]["end_ms"] / 1000.0,
                "words": words,
                "chapter": chapter["key"],
            }
            lines.append(line)
            idx += 1
            cursor += len(text)
        span = [l for l in lines if l["chapter"] == chapter["key"]]
        chapter_spans.append({
            "n": n,
            "key": chapter["key"],
            "title": chapter["title"],
            "start": span[0]["start"],
            "end": span[-1]["end"],
        })
    story: dict[str, Any] = {
        "title": title,
        "subtitle": subtitle,
        "duration": lines[-1]["end"] if lines else 0.0,
        "voice": voice,
        "timing": "measured",
        "lines": lines,
        "chapters": chapter_spans,
        "draft": False,
        "notes": notes or {},
    }
    if end_line is not None:
        story["end"] = end_line
    if recap is not None:
        story["recap"] = recap
    return story


def check_audio_lock(story: dict[str, Any]) -> list[str]:
    """Validate that a story.json is a self-consistent audio-locked timeline.

    Returns a list of problems; an empty list means the timeline is coherent:
    words are in non-decreasing order inside each line, nothing overlaps beyond
    tolerance, lines sit inside their chapter spans, and the duration matches.
    """
    problems: list[str] = []
    if story.get("draft"):
        problems.append("story is a draft; voice it before locking audio")
    lines = story.get("lines") or []
    if not lines:
        problems.append("story has no lines")
        return problems
    for line in lines:
        words = line.get("words") or []
        if not words:
            problems.append(f"line {line.get('i')}: no word timings")
            continue
        times = [w[1] for w in words]
        if any(b < a - OVERLAP_TOLERANCE_S for a, b in zip(times, times[1:])):
            problems.append(f"line {line.get('i')}: word times are not in order")
        if line["start"] > times[0] + OVERLAP_TOLERANCE_S:
            problems.append(f"line {line.get('i')}: line start is after its first word")
        if line["end"] < times[-1] - OVERLAP_TOLERANCE_S:
            problems.append(f"line {line.get('i')}: line end is before its last word")
    spans = [l["end"] for l in lines]
    if any(b < a - OVERLAP_TOLERANCE_S for a, b in zip(spans, spans[1:])):
        problems.append("lines are not in chronological order")
    for chapter in story.get("chapters") or []:
        members = [l for l in lines if l["chapter"] == chapter["key"]]
        if not members:
            problems.append(f"chapter {chapter.get('key')}: has no lines")
            continue
        if chapter["start"] > members[0]["start"] + OVERLAP_TOLERANCE_S:
            problems.append(f"chapter {chapter.get('key')}: span starts after its first line")
        if chapter["end"] < members[-1]["end"] - OVERLAP_TOLERANCE_S:
            problems.append(f"chapter {chapter.get('key')}: span ends before its last line")
    if abs(story.get("duration", 0.0) - lines[-1]["end"]) > OVERLAP_TOLERANCE_S:
        problems.append("story duration does not match the last line end")
    return problems
