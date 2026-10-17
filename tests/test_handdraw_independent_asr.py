"""Slow acceptance test for burned captions against an independent local ASR pass.

Set HANDDRAW_INDEPENDENT_ASR_FILMS to comma-separated completed render IDs, e.g.
L_1,P_1 or all eight IDs.  No network/model download is attempted.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = Path(os.environ.get("HANDDRAW_INDEPENDENT_ASR_ROOT", str(ROOT / ".tmp" / "vr4" / "runs"))).resolve()
MODEL = Path("/home/soffy/models/faster-whisper-large-v3-turbo")
PUNCTUATION = set("，。！？；：、,.!?;:…—·“”‘’（）()【】[]《》")


def _norm(value: str) -> str:
    return "".join(char for char in value if char.isalnum())


def _read_srt(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig").strip()
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", content):
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = re.fullmatch(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> "
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            lines[1].strip(),
        )
        if not match:
            raise AssertionError(f"Malformed SRT timing: {lines[1]!r}")
        h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, match.groups())
        cues.append({
            "start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
            "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
            "text": "".join(lines[2:]).strip(),
        })
    assert cues, f"No subtitle cues in {path}"
    return cues


def _edit_distance(left: str, right: str) -> int:
    if len(left) < len(right):
        left, right = right, left
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        next_row = [i]
        for j, b in enumerate(right, 1):
            next_row.append(min(
                next_row[-1] + 1,
                row[j] + 1,
                row[j - 1] + (a != b),
            ))
        row = next_row
    return row[-1]


def _audit_one(model: Any, render_id: str) -> dict[str, Any]:
    run = RUN_ROOT / render_id
    film = run / "outputs" / "film.mp4"
    srt_path = run / "outputs" / "editing" / "transcript.srt"
    alignment_path = run / "inputs" / "narration" / "alignment.json"
    for path in (film, srt_path, alignment_path):
        assert path.is_file(), f"{render_id} missing required artifact: {path}"

    cues = _read_srt(srt_path)
    alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    expected = _norm("".join(str(beat.get("text", "")) for beat in alignment["beats"]))

    segments, info = model.transcribe(
        str(film),
        language="zh",
        word_timestamps=True,
        vad_filter=False,
        initial_prompt="以下是面向2至6岁儿童的普通话幼儿故事。",
        beam_size=5,
        condition_on_previous_text=True,
    )
    words: list[dict[str, Any]] = []
    raw_words: list[str] = []
    for segment in segments:
        for word in segment.words or []:
            raw = str(word.word)
            raw_words.append(raw)
            for char in raw:
                if char.isalnum():
                    words.append({
                        "char": char,
                        "start": float(word.start),
                        "end": float(word.end),
                    })

    observed = "".join(word["char"] for word in words)
    cer = _edit_distance(expected, observed) / max(1, len(expected))

    cue_chars: list[str] = []
    ranges: list[tuple[int, int]] = []
    for cue in cues:
        begin = len(cue_chars)
        cue_chars.extend(_norm(cue["text"]))
        ranges.append((begin, len(cue_chars)))
    caption_text = "".join(cue_chars)

    # Sequence alignment is global to avoid matching a repeated phrase to an
    # unrelated later occurrence. Replacement blocks are mapped proportionally.
    matcher = difflib.SequenceMatcher(None, caption_text, observed, autojunk=False)
    mapping: dict[int, int] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
        elif tag == "replace" and i2 > i1 and j2 > j1:
            for offset in range(i2 - i1):
                mapping[i1 + offset] = min(
                    j2 - 1,
                    j1 + round(offset * (j2 - j1) / max(1, i2 - i1)),
                )

    errors: list[float] = []
    cue_results: list[dict[str, Any]] = []
    for cue_index, (cue, (begin, end)) in enumerate(zip(cues, ranges, strict=True), 1):
        prefix_end = min(end, begin + min(4, max(1, end - begin)))
        matched = [mapping[index] for index in range(begin, prefix_end) if index in mapping]
        onset_error = None
        if matched:
            observed_start = min(words[index]["start"] for index in matched)
            onset_error = float(cue["start"]) - observed_start
            errors.append(abs(onset_error))
        punctuation_start = bool(cue["text"] and cue["text"][0] in PUNCTUATION)
        cue_results.append({
            "cue": cue_index,
            "start": cue["start"],
            "text": cue["text"],
            "matched_prefix_chars": len(matched),
            "onset_error_seconds": round(onset_error, 3) if onset_error is not None else None,
            "starts_with_punctuation": punctuation_start,
        })

    p95 = (
        statistics.quantiles(errors, n=20, method="inclusive")[18]
        if len(errors) >= 2 else (max(errors) if errors else None)
    )
    caption_text_normalized = "".join(_norm(cue["text"]) for cue in cues)
    final_phrase_present = _norm("告诉身边的大人吧") in caption_text_normalized
    return {
        "render_id": render_id,
        "duration_seconds": round(float(info.duration), 3),
        "expected_characters": len(expected),
        "asr_characters": len(observed),
        "cer": round(cer, 5),
        "character_accuracy_percent": round((1 - cer) * 100, 2),
        "subtitle_cues": len(cues),
        "independent_asr_words": len(raw_words),
        "caption_onset_absolute_error_p95_seconds": round(p95, 3) if p95 is not None else None,
        "caption_onset_absolute_error_max_seconds": round(max(errors), 3) if errors else None,
        "unmatched_cues": sum(cue["onset_error_seconds"] is None for cue in cue_results),
        "punctuation_initial_cues": sum(cue["starts_with_punctuation"] for cue in cue_results),
        "final_interaction_phrase_present": final_phrase_present,
        "final_srt_cue": cues[-1]["text"],
        "cue_results": cue_results,
    }


@pytest.mark.slow
def test_completed_films_pass_independent_asr_and_caption_onset_gate() -> None:
    requested = [
        name.strip()
        for name in os.environ.get("HANDDRAW_INDEPENDENT_ASR_FILMS", "").split(",")
        if name.strip()
    ]
    if not requested:
        pytest.skip("Set HANDDRAW_INDEPENDENT_ASR_FILMS to completed full-render IDs")
    assert len(requested) >= 2, "Independent ASR gate requires at least two full films"
    assert MODEL.is_dir() and (MODEL / "model.bin").is_file(), (
        "The local large-v3-turbo model must exist; network downloads are disabled"
    )

    from faster_whisper import WhisperModel

    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", cpu_threads=4)
    reports = [_audit_one(model, render_id) for render_id in requested]

    report_path = ROOT / ".tmp" / "vr4" / "audit" / "test-independent-asr.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(reports, ensure_ascii=False, indent=2))

    for report in reports:
        assert report["cer"] <= 0.10, (
            f"{report['render_id']}: independent CER {report['cer']:.4f} > 0.10"
        )
        assert report["caption_onset_absolute_error_p95_seconds"] is not None
        assert report["caption_onset_absolute_error_p95_seconds"] <= 0.25, (
            f"{report['render_id']}: subtitle onset p95 "
            f"{report['caption_onset_absolute_error_p95_seconds']}s > 0.25s"
        )
        assert report["unmatched_cues"] == 0
        assert report["punctuation_initial_cues"] == 0
        assert report["final_interaction_phrase_present"]
