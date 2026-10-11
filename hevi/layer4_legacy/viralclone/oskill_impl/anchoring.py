"""Word-anchored template compilation and timeline layout algorithms (oskill layer)."""

from __future__ import annotations

import re
from typing import Any

from hevi.layer4_legacy.viralclone.oprim_impl.specs import (
    TemplateSegment,
    TemplateSpec,
    WordToken,
)
from hevi.studio.timeline import Timeline, TimelineClip

# CJK ideographs (incl. extension A and compatibility ideographs).
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def split_display_units(text: str) -> tuple[list[str], bool]:
    """Split caption text into karaoke display units.

    CJK text is split per character (whitespace dropped); Latin text is split
    into whitespace-delimited words. Returns ``(units, is_cjk)``.
    """
    if _CJK_RE.search(text):
        return [ch for ch in text if not ch.isspace()], True
    return text.split(), False


def assign_unit_times(
    units: list[str],
    start_s: float,
    end_s: float,
    aligned_words: list[WordToken],
) -> list[tuple[float, float]]:
    """Assign a time window to every display unit.

    Word-level ASR timestamps are used purely for *alignment*: when the ASR
    token count matches the display-unit count we snap one-to-one, otherwise we
    distribute the sentence window proportionally by character weight. The
    rendered text always comes from the template, never from ASR.
    """
    n = len(units)
    if n == 0:
        return []
    if aligned_words and len(aligned_words) == n:
        return [(float(w.start_s), float(w.end_s)) for w in aligned_words]

    span = max(0.05, float(end_s) - float(start_s))
    weights = [max(1, len(u)) for u in units]
    total = float(sum(weights))
    times: list[tuple[float, float]] = []
    cursor = float(start_s)
    for w in weights:
        dur = span * (w / total)
        times.append((cursor, cursor + dur))
        cursor += dur
    return times


def build_caption_line(
    text: str,
    start_s: float,
    end_s: float,
    aligned_words: list[WordToken],
) -> str:
    """Build an ASS karaoke line from the *template* text with word-anchored timing."""
    units, is_cjk = split_display_units(text)
    if not units:
        return text
    times = assign_unit_times(units, start_s, end_s, aligned_words)
    parts: list[str] = []
    for idx, (unit, (a, b)) in enumerate(zip(units, times, strict=False)):
        cs = max(1, int(round((b - a) * 100)))
        token = unit
        # Latin captions must keep inter-word spacing; attach it to the word.
        if not is_cjk and idx < len(units) - 1:
            token = unit + " "
        parts.append(f"{{\\k{cs}}}{token}")
    return "".join(parts)


def align_segments_to_word_timestamps(
    spec: TemplateSpec,
    slots: dict[str, Any],
    aligned_sentences: list[dict[str, Any]],
    aligned_words: list[WordToken],
) -> list[dict[str, Any]]:
    """Compute exact time windows for segments and anchors based on real word timestamps."""
    compiled_segments: list[dict[str, Any]] = []

    for s_idx, segment in enumerate(spec.segments):
        # Find matching sentence from aligned results
        matching_sent = None
        if s_idx < len(aligned_sentences):
            matching_sent = aligned_sentences[s_idx]
        elif aligned_sentences:
            matching_sent = aligned_sentences[-1]

        start_s = float(matching_sent.get("start_s", 0.0)) if matching_sent else 0.0
        end_s = float(matching_sent.get("end_s", start_s + 2.0)) if matching_sent else start_s + 2.0
        # Caption text is ALWAYS the filled template slot. Never fall back to ASR
        # text (homophones) or the wrong slot; use a neutral role label if empty.
        text = str(slots.get(segment.narration_slot) or "").strip()
        if not text:
            text = str(segment.role).replace("_", " ").strip().title()

        # Resolve visual anchors relative to this sentence's word timestamps
        resolved_anchors: list[dict[str, Any]] = []
        sent_words = [
            w for w in aligned_words
            if start_s - 0.05 <= w.start_s <= end_s + 0.05
        ]

        for anchor in segment.anchors:
            anchor_start = start_s + anchor.relative_delay_s
            # If word offset is given and words are found, snap to that word
            if sent_words and 0 <= anchor.word_offset_idx < len(sent_words):
                w = sent_words[anchor.word_offset_idx]
                anchor_start = w.start_s + anchor.relative_delay_s

            resolved_anchors.append(
                {
                    "event_type": anchor.event_type,
                    "start_s": round(max(0.0, anchor_start), 3),
                    "duration_s": round(max(0.5, anchor.duration_s), 3),
                    "target_slot": anchor.target_slot,
                    "parameters": anchor.parameters,
                }
            )

        compiled_segments.append(
            {
                "segment_id": segment.segment_id,
                "role": segment.role,
                "text": text,
                "start_s": round(start_s, 3),
                "end_s": round(end_s, 3),
                "duration_s": round(max(0.2, end_s - start_s), 3),
                "anchors": resolved_anchors,
                "caption_style": segment.caption_style,
            }
        )

    return compiled_segments


def build_timeline_from_anchors(
    timeline_id: str,
    title: str,
    spec: TemplateSpec,
    compiled_segments: list[dict[str, Any]],
    aligned_words: list[WordToken],
    *,
    broll_sources: list[str] | None = None,
    product_video_path: str = "",
    bgm_path: str = "",
) -> Timeline:
    """Build canonical Hevi Timeline JSON structure anchored on speech timestamps."""
    clips: list[TimelineClip] = []
    brolls = list(broll_sources or [])
    broll_cursor = 0

    # Video track: cuts derived from segment boundaries and visual anchors
    for idx, seg in enumerate(compiled_segments):
        start_s = seg["start_s"]
        dur_s = seg["duration_s"]
        role = seg["role"]

        # Select video source based on anchors or role
        has_product = any(a["event_type"] == "product_card" for a in seg["anchors"])
        if has_product and product_video_path:
            src = product_video_path
        elif brolls:
            src = brolls[broll_cursor % len(brolls)]
            broll_cursor += 1
        else:
            src = product_video_path or "source_default"

        clips.append(
            TimelineClip(
                clip_id=f"v_{idx:03d}_{role}",
                track="video",
                start_s=start_s,
                duration_s=dur_s,
                label=f"{role}: {seg['text'][:15]}",
                action="keep",
                source=src,
                text=seg["text"],
                transition="cut" if idx == 0 else "dissolve",
                effect="none",
            )
        )

        # Audio track: VO clips
        clips.append(
            TimelineClip(
                clip_id=f"a_{idx:03d}_{role}",
                track="audio",
                start_s=start_s,
                duration_s=dur_s,
                label=f"VO_{role}",
                action="keep",
                text=seg["text"],
            )
        )

    # Captions track: one caption clip per aligned word or sentence chunk
    for w_idx, word in enumerate(aligned_words):
        dur = max(0.1, word.end_s - word.start_s)
        clips.append(
            TimelineClip(
                clip_id=f"c_{w_idx:04d}",
                track="captions",
                start_s=round(word.start_s, 3),
                duration_s=round(dur, 3),
                label=word.word[:12],
                action="keep",
                text=word.word,
            )
        )

    return Timeline(
        timeline_id=timeline_id,
        title=title,
        clips=clips,
        bgm=bgm_path,
        fps=spec.fps,
    )


def format_ass_time(seconds: float) -> str:
    """Format seconds into ASS timestamp h:mm:ss.cc."""
    sec = max(0.0, seconds)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_subtitles(
    words: list[WordToken],
    sentences: list[dict[str, Any]],
    width: int,
    height: int,
    *,
    font_name: str = "Noto Sans CJK SC",
    font_size: int = 42,
    watermark_text: str = "",
    watermark_duration_s: float = 2.5,
    watermark_font_size: int = 36,
) -> str:
    """Generate ASS subtitle script with karaoke/highlight word timing and optional AI watermark."""
    short_edge = min(width, height)
    wm_size = max(watermark_font_size, int(short_edge * 0.05))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,70,1
Style: Highlight,{font_name},{font_size},&H0033E6FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,20,20,70,1
Style: Watermark,{font_name},{wm_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,2,0,7,24,24,24,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []

    # AI Watermark event (GB 45438-2025: duration >= 2s, short edge >= 5%).
    # No fade-in so the very first frame carries the full-size mark for pixel QA.
    if watermark_text:
        wm_start = format_ass_time(0.0)
        wm_end = format_ass_time(watermark_duration_s)
        events.append(
            f"Dialogue: 2,{wm_start},{wm_end},Watermark,,0,0,0,,{{\\fad(0,150)}}[ {watermark_text} ]"
        )

    # Word/sentence captions. Text is always the template slot text; ASR word
    # timestamps are only used to align karaoke timing (never as caption text).
    for sent in sentences:
        s_start = float(sent.get("start_s", 0.0))
        s_end = float(sent.get("end_s", s_start + 1.0))
        text = str(sent.get("text") or "")
        if not text.strip():
            continue

        # Find ASR words within this sentence for alignment only.
        swords = [w for w in words if s_start - 0.05 <= w.start_s <= s_end + 0.05]
        line_text = build_caption_line(text, s_start, s_end, swords)
        events.append(
            f"Dialogue: 0,{format_ass_time(s_start)},{format_ass_time(s_end)},Default,,0,0,0,,{line_text}"
        )

    return header + "\n".join(events) + "\n"
