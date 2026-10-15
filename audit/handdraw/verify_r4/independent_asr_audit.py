#!/usr/bin/env python3
"""Independent CPU Whisper timing audit for finished Handdraw MP4/SRT pairs.

Uses a separately installed faster-whisper large-v3-turbo model, not the
production caption aligner's local small model. Writes measurements to the
user-supplied path or stdout; no network or paid API is used.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
from array import array
from pathlib import Path
from statistics import median
from typing import Any

MODEL = Path("/home/soffy/models/faster-whisper-large-v3-turbo")
TIMECODE = re.compile(
    r"(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})"
)
PUNCTUATION = set("，。！？；：、,.!?;:…—·「」『』（）()《》<>\"'“”‘’ \t\r\n")


def stamp(match: re.Match[str], prefix: str) -> float:
    return (
        int(match.group(prefix + "h")) * 3600
        + int(match.group(prefix + "m")) * 60
        + int(match.group(prefix + "s"))
        + int(match.group(prefix + "ms")) / 1000
    )


def normalise(text: str) -> list[str]:
    return [
        ch.lower() for ch in text
        if ch not in PUNCTUATION and (ch.isalnum() or "\u3400" <= ch <= "\u9fff")
    ]


def parse_srt(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues: list[dict[str, Any]] = []
    for block in blocks:
        lines = block.splitlines()
        time_line = next((line for line in lines if TIMECODE.search(line)), None)
        if not time_line:
            continue
        match = TIMECODE.search(time_line)
        assert match is not None
        time_line_index = lines.index(time_line)
        text = "".join(lines[time_line_index + 1:]).strip()
        cues.append({
            "start": stamp(match, "s"),
            "end": stamp(match, "e"),
            "text": text,
        })
    if not cues:
        raise ValueError(f"no subtitle cues parsed from {path}")
    return cues


def adjust_words_for_audio_silence(
    words: list[dict[str, Any]], video: Path, *, threshold: float = 0.005,
) -> int:
    """Correct word timestamps spanning leading silence using decoded MP4 audio."""
    completed = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(video), "-map", "0:a:0",
            "-ac", "1", "-ar", "16000", "-f", "s16le", "-",
        ],
        check=True, capture_output=True,
    )
    samples = array("h")
    samples.frombytes(completed.stdout)
    if not samples:
        raise ValueError(f"independent audio silence gate received empty audio: {video}")
    rate = 16000
    frame_samples = 320  # 20 ms
    active: list[bool] = []
    for offset in range(0, len(samples), frame_samples):
        frame = samples[offset:offset + frame_samples]
        rms = (sum(int(value) * int(value) for value in frame) / max(1, len(frame))) ** 0.5 / 32768.0
        active.append(rms >= threshold)

    adjusted = 0
    duration = len(samples) / rate
    frame_seconds = frame_samples / rate
    for word in words:
        start = max(0.0, float(word["start"]))
        end = min(duration, max(start, float(word["end"])))
        first = min(len(active) - 1, int(start * rate / frame_samples))
        last = min(len(active), max(first + 1, int(end * rate / frame_samples) + 1))
        active_indices = [index for index in range(first, last) if active[index]]
        if not active_indices:
            continue
        clusters: list[list[int]] = []
        for index in active_indices:
            if not clusters or (index - clusters[-1][-1] - 1) * frame_seconds >= 0.24:
                clusters.append([index, index])
            else:
                clusters[-1][-1] = index

        next_start: float | None = None
        start_is_active = bool(active[first])
        token_characters = len(normalise(str(word.get("text", ""))))
        span = end - start
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


def score_alignment(
    cues: list[dict[str, Any]], words: list[dict[str, Any]],
) -> dict[str, Any]:
    """Align each cue to an independent ASR word window near its displayed onset.

    Global LCS alone confuses repeated short Chinese phrases and ASR words
    hallucinated over the silent cover. This audit compares each actual SRT
    cue against word-timestamped characters within a local time window, scores
    text agreement, then resolves duplicate phrases by nearest real speech onset.
    It still fails when a cue cannot be independently matched.
    """
    asr_chars: list[str] = []
    asr_spans: list[dict[str, float]] = []
    for word in words:
        for char in normalise(str(word.get("text", ""))):
            asr_chars.append(char)
            asr_spans.append({
                "start": float(word["start"]),
                "end": float(word["end"]),
            })

    errors: list[float] = []
    details: list[dict[str, Any]] = []
    unmatched: list[int] = []
    punctuation_leading = [
        i for i, cue in enumerate(cues)
        if str(cue["text"]).lstrip() and str(cue["text"]).lstrip()[0] in PUNCTUATION
    ]

    for cue_index, cue in enumerate(cues):
        target = normalise(str(cue["text"]))
        if not target:
            unmatched.append(cue_index)
            continue
        lower = max(0.0, float(cue["start"]) - 2.0)
        upper = float(cue["start"]) + 1.0
        first_chars = set(target[:min(4, len(target))])
        candidates: list[tuple[float, float, float, str]] = []

        for index, (character, timing) in enumerate(zip(asr_chars, asr_spans, strict=True)):
            if character not in first_chars:
                continue
            if not lower <= timing["start"] <= upper:
                continue
            for extra in (0, 2, 4):
                window = asr_chars[index:index + len(target) + extra]
                if not window:
                    continue
                matcher = difflib.SequenceMatcher(None, target, window, autojunk=False)
                blocks = [block for block in matcher.get_matching_blocks() if block.size]
                usable = [block for block in blocks if block.a < min(4, len(target))]
                if not usable:
                    continue
                first = min(usable, key=lambda block: block.a)
                actual_start = float(asr_spans[index + first.b]["start"])
                candidates.append((
                    matcher.ratio(),
                    -abs(actual_start - float(cue["start"])),
                    actual_start,
                    target[first.a],
                ))

        if not candidates:
            unmatched.append(cue_index)
            continue
        candidates.sort(reverse=True)
        score, _proximity, actual_start, matched_char = candidates[0]
        if score < 0.22:
            unmatched.append(cue_index)
            continue
        error = float(cue["start"]) - actual_start
        errors.append(abs(error))
        details.append({
            "cue_index": cue_index + 1,
            "cue_start_seconds": round(float(cue["start"]), 3),
            "independent_speech_onset_seconds": round(actual_start, 3),
            "signed_cue_minus_speech_seconds": round(error, 3),
            "absolute_error_seconds": round(abs(error), 3),
            "cue_text": cue["text"],
            "matched_subtitle_char": matched_char,
            "local_match_score": round(score, 4),
        })

    if not errors:
        raise ValueError("independent ASR transcript could not align to subtitle characters")
    ordered = sorted(errors)
    p95_index = min(len(ordered) - 1, max(0, int(0.95 * (len(ordered) - 1) + 0.5)))
    return {
        "cue_count": len(cues),
        "matched_cue_count": len(details),
        "unmatched_cue_indices_1based": [i + 1 for i in unmatched],
        "matching_coverage": round(len(details) / len(cues), 4),
        "median_absolute_error_seconds": round(median(errors), 4),
        "p95_absolute_error_seconds": round(ordered[p95_index], 4),
        "max_absolute_error_seconds": round(max(errors), 4),
        "leading_punctuation_cue_indices_1based": [i + 1 for i in punctuation_leading],
        "cue_details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pairs", nargs="+", metavar="MP4,SRT",
        help="finished film file and its actual SRT sidecar (may pass multiple pairs)",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from faster_whisper import WhisperModel

    if not MODEL.is_dir():
        raise FileNotFoundError(f"local independent CPU ASR model not found: {MODEL}")
    model = WhisperModel(
        str(MODEL), device="cpu", compute_type="int8", cpu_threads=4,
    )
    results = {
        "model": str(MODEL),
        "device": "cpu",
        "compute_type": "int8",
        "pairs": [],
    }
    for pair in args.pairs:
        video_raw, subtitle_raw = pair.split(",", 1)
        video, subtitle = Path(video_raw), Path(subtitle_raw)
        if not video.is_file() or not subtitle.is_file():
            raise FileNotFoundError(f"missing independent ASR input: {video} / {subtitle}")
        cues = parse_srt(subtitle)
        segments, _info = model.transcribe(
            str(video), language="zh", word_timestamps=True, vad_filter=False,
            beam_size=5, initial_prompt="以下是普通话的句子。",
        )
        words = []
        transcript = []
        for segment in segments:
            transcript.append(segment.text)
            for word in segment.words or []:
                token = str(word.word).strip()
                if token:
                    words.append({
                        "text": token,
                        "start": float(word.start),
                        "end": float(word.end),
                    })
        silence_adjusted_word_count = adjust_words_for_audio_silence(words, video)
        score = score_alignment(cues, words)
        score.update({
            "silence_adjusted_word_count": silence_adjusted_word_count,
            "video": str(video),
            "subtitle": str(subtitle),
            "duration_seconds": round(max((w["end"] for w in words), default=0.0), 3),
            "asr_word_count": len(words),
            "asr_transcript": "".join(transcript),
        })
        results["pairs"].append(score)
        print(
            f"{video.name}: cues={score['cue_count']} "
            f"matched={score['matched_cue_count']} "
            f"coverage={score['matching_coverage']:.1%} "
            f"p95={score['p95_absolute_error_seconds']:.3f}s "
            f"max={score['max_absolute_error_seconds']:.3f}s",
            flush=True,
        )

    results["all_p95_seconds"] = max(
        pair["p95_absolute_error_seconds"] for pair in results["pairs"]
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
