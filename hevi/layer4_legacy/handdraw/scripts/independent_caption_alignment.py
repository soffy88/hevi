"""Retiming of production subtitles against a second, local CPU ASR model.

The primary narration builder uses the small Whisper snapshot. This module uses
local large-v3-turbo word timestamps on the finished PCM narration master, then
moves both the visible caption events and their SRT cue records to those
independently measured word onsets before final video encoding. No download or
network request is made.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import wave
from array import array
from itertools import pairwise
from pathlib import Path
from typing import Any

MODEL_DIR = Path(os.environ.get(
    "HANDDRAW_INDEPENDENT_ASR_MODEL",
    "/home/soffy/models/faster-whisper-large-v3-turbo",
))


def _norm(text: str) -> str:
    return "".join(
        char.lower()
        for char in text
        if char.isalnum() or "\u3400" <= char <= "\u9fff"
    )


def _char_timing(words: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, float]]]:
    characters: list[str] = []
    spans: list[dict[str, float]] = []
    for word in words:
        for char in _norm(str(word["text"])):
            characters.append(char)
            spans.append({"start": float(word["start"]), "end": float(word["end"])})
    return characters, spans


def _match_cue(
    cue_text: str,
    old_start: float,
    asr_chars: list[str],
    spans: list[dict[str, float]],
) -> tuple[float, float, float]:
    """Find the best text-matching local ASR window near the current cue.

    The temporal window disambiguates repeated short words; the timestamp is
    selected from the independent ASR output, not inferred from subtitle timing.
    """
    target = _norm(cue_text)
    if not target or not asr_chars:
        raise ValueError("cannot align an empty cue or empty independent ASR transcript")

    first_chars = set(target[: min(4, len(target))])
    candidates: list[tuple[float, float, float, float]] = []
    lower, upper = max(0.0, old_start - 2.0), old_start + 1.0
    for index, (character, timing) in enumerate(zip(asr_chars, spans, strict=True)):
        if character not in first_chars:
            continue
        start = timing["start"]
        if start < lower or start > upper:
            continue
        for extra in (0, 2, 4):
            window = asr_chars[index:index + max(1, len(target) + extra)]
            if not window:
                continue
            matcher = difflib.SequenceMatcher(
                None, target, window, autojunk=False,
            )
            blocks = [block for block in matcher.get_matching_blocks() if block.size]
            usable = [block for block in blocks if block.a < min(4, len(target))]
            if not usable:
                continue
            first = min(usable, key=lambda block: block.a)
            matched_start = spans[index + first.b]["start"]
            score = matcher.ratio()
            # Text agreement dominates. Time proximity breaks ties among duplicate
            # phrases; it does not make a low-similarity transcript a match.
            candidates.append((
                score,
                -abs(matched_start - old_start),
                matched_start,
                max(spans[index + block.b + block.size - 1]["end"] for block in blocks),
            ))
    if not candidates:
        raise RuntimeError(f"no independent ASR text match for cue at {old_start:.3f}s: {cue_text!r}")
    candidates.sort(reverse=True)
    score, _proximity, start, end = candidates[0]
    if score < 0.22:
        raise RuntimeError(f"low independent ASR match score {score:.3f} for cue: {cue_text!r}")
    return start, end, score


def _adjust_word_starts_for_silence(
    words: list[dict[str, Any]], audio_path: Path | str, *, threshold: float = 0.005,
) -> int:
    """Move hallucinated ASR word onsets out of leading silence in their span.

    Whisper can assign a token to a long span beginning before speech (often on
    the silent cover). This uses the source PCM's 20 ms RMS windows to place the
    token at the first audible window inside that already-recognized word span.
    It does not change transcript text, word ends, or starts that already contain
    audible energy.
    """
    with wave.open(str(audio_path), "rb") as source:
        rate = source.getframerate()
        channels = source.getnchannels()
        width = source.getsampwidth()
        if width != 2:
            raise ValueError(f"caption silence gate expects 16-bit PCM WAV, got {width * 8}-bit")
        if rate <= 0 or channels <= 0:
            raise ValueError("caption silence gate received invalid WAV format")
        frame_samples = max(1, round(rate * 0.02))
        samples_per_frame = frame_samples * channels
        pcm = array("h")
        while True:
            chunk = source.readframes(frame_samples)
            if not chunk:
                break
            values = array("h")
            values.frombytes(chunk)
            if len(values) < samples_per_frame:
                values.extend([0] * (samples_per_frame - len(values)))
            energy = sum(int(value) * int(value) for value in values)
            rms = (energy / max(1, len(values))) ** 0.5 / 32768.0
            pcm.append(1 if rms >= threshold else 0)
    if not pcm:
        raise ValueError(f"caption silence gate received empty WAV: {audio_path}")

    adjusted = 0
    duration = len(pcm) * frame_samples / rate
    frame_seconds = frame_samples / rate
    for word in words:
        start = max(0.0, float(word["start"]))
        end = min(duration, max(start, float(word["end"])))
        first = min(len(pcm) - 1, int(start * rate / frame_samples))
        last = min(len(pcm), max(first + 1, int(end * rate / frame_samples) + 1))
        active_indices = [index for index in range(first, last) if pcm[index]]
        if not active_indices:
            continue
        clusters: list[list[int]] = []
        for index in active_indices:
            if not clusters or (index - clusters[-1][-1] - 1) * frame_seconds >= 0.24:
                clusters.append([index, index])
            else:
                clusters[-1][-1] = index

        next_start: float | None = None
        start_is_active = bool(pcm[first])
        token_characters = len(_norm(str(word.get("text", ""))))
        span = end - start
        # A long single-character token that straddles a silent pause commonly
        # receives one timestamp spanning two distinct audible syllable regions.
        # Its onset is the final active cluster only when that cluster follows a
        # substantial gap and sits at the end of the token's span.
        if (
            start_is_active
            and token_characters <= 2
            and span >= 0.70
            and len(clusters) > 1
            and (clusters[-1][0] - clusters[-2][1] - 1) * frame_seconds >= 0.24
            and end - clusters[-1][0] * frame_seconds <= 0.50
        ):
            next_start = clusters[-1][0] * frame_seconds
        elif not start_is_active:
            next_start = clusters[0][0] * frame_seconds
        if next_start is not None and next_start > start:
            word["start"] = round(next_start, 6)
            adjusted += 1
    return adjusted


def _reconcile_page_boundaries(timeline: dict[str, Any]) -> list[dict[str, float]]:
    """Keep independently retimed captions and their artwork on valid page clocks.

    Piper's beat clock and independent word timestamps can move a caption across
    the originally planned page transition. Use the speech gap between the last
    caption on one page and the first caption on the next as the true cut point,
    then translate that page's non-caption events together with its start time.
    Caption events themselves are already tied to the measured audio and must not
    be shifted a second time.
    """
    pages = timeline.get("pages", [])
    if not pages:
        raise ValueError("cannot reconcile subtitle timing without timeline pages")

    page_captions: list[list[dict[str, Any]]] = []
    for index, page in enumerate(pages):
        captions = sorted(
            (event for event in page.get("events", []) if event.get("caption") is True),
            key=lambda event: float(event["start"]),
        )
        if not captions:
            raise ValueError(f"timeline page {index + 1} has no caption events")
        page_captions.append(captions)

    boundaries = [float(pages[0]["start"])]
    for index in range(1, len(pages)):
        left = float(page_captions[index - 1][-1].get("hide", page_captions[index - 1][-1]["end"]))
        right = float(page_captions[index][0]["start"])
        if left >= right:
            raise ValueError(
                f"retimed captions overlap across page boundary {index}: {left:.3f} >= {right:.3f}"
            )
        boundaries.append((left + right) / 2.0)
    boundaries.append(float(pages[-1]["end"]))

    report: list[dict[str, float]] = []
    for index, page in enumerate(pages):
        old_start = float(page["start"])
        old_end = float(page["end"])
        new_start = boundaries[index]
        new_end = boundaries[index + 1]
        if not new_start < new_end:
            raise ValueError(f"retimed page {index + 1} would have an empty interval")
        shift = new_start - old_start

        # Preserve within-page motion/event ordering while moving the visual clock
        # onto the audio-aligned page. Caption events remain on their ASR clocks.
        for event in page.get("events", []):
            if event.get("caption") is True:
                continue
            for key in ("start", "end", "hide"):
                value = event.get(key)
                if isinstance(value, (int, float)):
                    event[key] = round(float(value) + shift, 6)

        for key in ("speech_start", "last_drawing_end", "first_drawing_start"):
            value = page.get(key)
            if isinstance(value, (int, float)):
                page[key] = round(float(value) + shift, 6)
        # Each page's last aligned cue is the measured end of its spoken content;
        # the old beat estimator can extend beyond it and overlap the next page.
        page["speech_end"] = round(
            float(page_captions[index][-1].get("hide", page_captions[index][-1]["end"])),
            6,
        )
        page["start"] = round(new_start, 6)
        page["end"] = round(new_end, 6)

        # Real ASR can shorten a beat compared with the original storyboard's
        # duration estimate. Compress the drawing clock uniformly, if needed,
        # so every stroke is finished at least 450 ms before the final word ends.
        # This changes event timing itself (not just the reported metadata), keeps
        # stroke order/gaps intact, and leaves measured caption timestamps alone.
        drawing_events = [
            event for event in page.get("events", [])
            if event.get("caption") is not True
            and isinstance(event.get("start"), (int, float))
            and isinstance(event.get("end"), (int, float))
        ]
        drawing_end = max((float(event["end"]) for event in drawing_events), default=new_start)
        drawing_target = float(page["speech_end"]) - 0.45
        drawing_scale = 1.0
        if drawing_end > drawing_target:
            drawing_span = drawing_end - new_start
            allowed_span = drawing_target - new_start
            if drawing_span <= 0 or allowed_span <= 0:
                raise ValueError(
                    f"page {index + 1} has no room for a 450 ms drawing completion hold"
                )
            drawing_scale = allowed_span / drawing_span
            for event in drawing_events:
                for key in ("start", "end", "hide"):
                    value = event.get(key)
                    if isinstance(value, (int, float)):
                        event[key] = round(new_start + (float(value) - new_start) * drawing_scale, 6)
            drawing_end = max(float(event["end"]) for event in drawing_events)

        page["last_drawing_end"] = round(drawing_end, 6)
        if drawing_events:
            page["first_drawing_start"] = round(
                min(float(event["start"]) for event in drawing_events), 6
            )
        completion_hold = float(page["speech_end"]) - drawing_end
        if completion_hold < 0.45 - 0.00001:
            raise ValueError(
                f"page {index + 1} drawing hold is {completion_hold:.3f}s, below 0.450s"
            )
        report.append({
            "page": float(index + 1),
            "old_start": round(old_start, 6),
            "old_end": round(old_end, 6),
            "new_start": round(new_start, 6),
            "new_end": round(new_end, 6),
            "event_shift_seconds": round(shift, 6),
            "drawing_time_scale": round(drawing_scale, 8),
            "drawing_completion_hold_seconds": round(completion_hold, 6),
        })

    return report


def _clamp_final_cue_hold(planned: list[dict[str, Any]], media_end: float) -> float:
    """Keep the last reading hold inside the film when ASR moved its onset later.

    The final interaction cue keeps its original beat span even when the
    independent word timestamps move its onset closer to the end. Without this
    clamp its reading hold ran past the end of the narration, and the subtitle
    contract (every cue inside its page) rejected the whole render. Returns the
    number of seconds removed from the final hold.
    """
    final_entry = planned[-1]
    overflow = float(final_entry["end"]) - media_end
    if overflow <= 0.0:
        return 0.0
    if media_end <= float(final_entry["start"]) + 0.20:
        raise RuntimeError(
            "final caption cannot fit before the end of narration: "
            f"start={float(final_entry['start']):.3f}s media_end={media_end:.3f}s"
        )
    final_entry["end"] = media_end
    return round(overflow, 6)


def retime_timeline_captions(root: Path | str, timeline: dict[str, Any]) -> dict[str, Any]:
    """Apply independent word-level timings to timeline cues and visual events."""
    from faster_whisper import WhisperModel

    root = Path(root).resolve()
    narration = root / "work" / "narration.wav"
    timeline_path = root / "work" / "timeline.json"
    if not narration.is_file():
        raise FileNotFoundError(f"independent caption alignment requires {narration}")
    if not (MODEL_DIR / "model.bin").is_file():
        raise FileNotFoundError(
            f"local independent ASR model missing: {MODEL_DIR}; network downloads are disabled"
        )

    model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8", cpu_threads=4)
    segments, _info = model.transcribe(
        str(narration),
        language="zh",
        word_timestamps=True,
        vad_filter=False,
        beam_size=5,
        initial_prompt="以下是普通话的句子。",
        condition_on_previous_text=True,
    )
    words: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.words or []:
            token = str(word.word).strip()
            if token and _norm(token):
                words.append({
                    "text": token,
                    "start": float(word.start),
                    "end": float(word.end),
                })
    if not words:
        raise RuntimeError("independent large-v3-turbo ASR returned no word timestamps")
    silence_adjusted_word_count = _adjust_word_starts_for_silence(words, narration)

    asr_chars, spans = _char_timing(words)
    cues = timeline.get("cues", [])
    caption_events = [
        event
        for page in timeline.get("pages", [])
        for event in page.get("events", [])
        if event.get("caption") is True
    ]
    if not cues or len(caption_events) != len(cues):
        raise ValueError(
            f"caption alignment cardinality mismatch: cues={len(cues)} events={len(caption_events)}"
        )

    cover_start = float(timeline.get("cover_seconds", 1.0))
    original = [{"start": float(cue["start"]), "end": float(cue["end"])} for cue in cues]
    planned: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        old_start, old_end = original[index]["start"], original[index]["end"]
        speech_start, speech_end, match_score = _match_cue(
            str(cue.get("text", "")), old_start, asr_chars, spans,
        )
        target_start = speech_start
        # Keep the title card silent; word-level ASR can hallucinate during silence.
        if index == 0:
            target_start = max(cover_start, target_start)
        # Preserve ordering for rare near-adjacent Chinese character timestamps.
        if planned:
            target_start = max(target_start, planned[-1]["start"] + 0.12)

        planned.append({
            "start": target_start,
            "end": target_start + max(0.20, old_end - old_start),
            "speech_start": speech_start,
            "speech_end": speech_end,
            "match_score": match_score,
            "old_start": old_start,
            "old_end": old_end,
        })

    # Clamp each reading hold to before the next caption starts. This is also
    # required by the subtitle contract, which forbids overlap and empty cues.
    for index, entry in enumerate(planned):
        duration = max(0.20, original[index]["end"] - original[index]["start"])
        end = entry["start"] + duration
        if index + 1 < len(planned):
            end = min(end, planned[index + 1]["start"] - 0.025)
        if end <= entry["start"]:
            raise RuntimeError(f"caption {index + 1} cannot fit between independently timed neighboring cues")
        entry["end"] = end

    # The final cue keeps its original beat span even when the independent ASR
    # moved its onset later, so its reading hold can run past the end of the
    # narration. The subtitle contract also requires every cue to stay inside
    # its page, and the last page ends with the media, so clamp the final hold
    # to the measured end of the film instead of failing the whole render.
    final_entry = planned[-1]
    final_overflow_seconds = _clamp_final_cue_hold(
        planned,
        max(
            float(timeline.get("duration", final_entry["end"])),
            float(timeline["pages"][-1]["end"]),
        ),
    )

    for cue, event, entry in zip(cues, caption_events, planned, strict=True):
        cue["start"] = round(entry["start"], 6)
        cue["end"] = round(entry["end"], 6)
        event["start"] = cue["start"]
        event["end"] = cue["end"]
        event["hide"] = cue["end"]

    page_boundary_report = _reconcile_page_boundaries(timeline)

    for page in timeline.get("pages", []):
        caption_starts = [
            event["start"] for event in page.get("events", [])
            if event.get("caption") is True
        ]
        if any(a >= b for a, b in pairwise(caption_starts)):
            raise ValueError("independent caption retiming produced non-monotonic page events")

    timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    editing_dir = root / "outputs" / "editing"
    editing_dir.mkdir(parents=True, exist_ok=True)

    def srt_stamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"

    srt_blocks = [
        f"{index + 1}\n{srt_stamp(cue['start'])} --> {srt_stamp(cue['end'])}\n{cue['text']}"
        for index, cue in enumerate(cues)
    ]
    (editing_dir / "transcript.srt").write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8")

    report = {
        "model": str(MODEL_DIR),
        "device": "cpu",
        "compute_type": "int8",
        "source": str(narration),
        "source_sha256": hashlib.sha256(narration.read_bytes()).hexdigest(),
        "cue_count": len(cues),
        "final_cue_hold_clamped_seconds": round(final_overflow_seconds, 6),
        "silence_adjusted_word_count": silence_adjusted_word_count,
        "page_boundaries": page_boundary_report,
        "max_absolute_retime_seconds": round(max(
            abs(item["start"] - item["old_start"]) for item in planned
        ), 4),
        "cues": [{
            "text": cue["text"],
            "old_start": item["old_start"],
            "independent_word_start": round(item["speech_start"], 6),
            "new_start": cue["start"],
            "new_end": cue["end"],
            "match_score": round(item["match_score"], 4),
        } for cue, item in zip(cues, planned, strict=True)],
    }
    (root / "work" / "independent-caption-alignment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report
