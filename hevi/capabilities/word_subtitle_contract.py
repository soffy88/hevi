"""Word-level subtitle contract (``edit.word_subtitle_contract``).

Clean-room method intake: a word-level transcript becomes an
explicit contract shared by cutting, karaoke subtitling and
Remotion rendering. The contract fixes three things that must
never drift between stages:

* Absolute timestamps: every word time is in source seconds,
  never relative to a clip or a line.
* Paragraph order: paragraph ids, when present, must appear in
  non-decreasing order and must not return to an earlier id.
* No overlap, no reorder: words must be sorted by start time and
  a word must not start before the previous word ends (within
  1 millisecond tolerance).

Karaoke lines are derived deterministically from the contract:
words are grouped within a paragraph, at most 10 words or 5
seconds per line, whichever comes first. A line's text is the
space-joined words; its times are the first word's start and the
last word's end. No word is dropped, split or reworded.

Failure contract: empty input, missing fields, negative or
end<=start times, out-of-order words, overlapping words, a
paragraph id that goes backwards, or a word ending past the
declared source duration all raise CapabilityError. The
contract never silently repairs a bad transcript.
"""

from __future__ import annotations

import json
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
_TOL = 1e-3
_MAX_WORDS_PER_LINE = 10
_MAX_LINE_SEC = 5.0


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"edit.word_subtitle_contract: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.word_subtitle_contract: {what} must be a non-empty string")
    return value.strip()


def build_contract(transcript: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(transcript, dict):
        raise CapabilityError("edit.word_subtitle_contract: transcript must be a JSON object")
    words_raw = transcript.get("words")
    if not isinstance(words_raw, list) or not words_raw:
        raise CapabilityError("edit.word_subtitle_contract: words must be a non-empty list")
    source_duration = transcript.get("source_duration_sec")
    if source_duration is not None:
        source_duration = _require_num(source_duration, "source_duration_sec")
        if source_duration <= 0:
            raise CapabilityError("edit.word_subtitle_contract: source_duration_sec must be > 0")
    words: list[dict[str, Any]] = []
    prev_start = -1.0
    prev_end = -1.0
    prev_para: str | None = None
    seen_paras: list[str] = []
    for i, w in enumerate(words_raw):
        if not isinstance(w, dict):
            raise CapabilityError(f"edit.word_subtitle_contract: word {i} must be a JSON object")
        text = _require_str(w.get("word"), f"word {i}.word")
        start = _require_num(w.get("start_sec"), f"word {i}.start_sec")
        end = _require_num(w.get("end_sec"), f"word {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.word_subtitle_contract: word {i} has an invalid time range")
        if start < prev_start - _TOL:
            raise CapabilityError(f"edit.word_subtitle_contract: word {i} is out of order")
        if start < prev_end - _TOL:
            raise CapabilityError(f"edit.word_subtitle_contract: word {i} overlaps the previous word")
        if source_duration is not None and end > source_duration + _TOL:
            raise CapabilityError(f"edit.word_subtitle_contract: word {i} ends past source_duration_sec")
        para = w.get("paragraph_id", "p0")
        if not isinstance(para, str) or not para:
            raise CapabilityError(f"edit.word_subtitle_contract: word {i}.paragraph_id must be a non-empty string")
        if prev_para is not None and para != prev_para and para in seen_paras[:-1]:
            raise CapabilityError("edit.word_subtitle_contract: paragraph_id must not return to an earlier paragraph")
        if para not in seen_paras:
            seen_paras.append(para)
        prev_para = para
        prev_start, prev_end = start, end
        words.append({"word": text, "start_sec": start, "end_sec": end, "paragraph_id": para})
    paragraphs: list[dict[str, Any]] = []
    for para in seen_paras:
        pw = [w for w in words if w["paragraph_id"] == para]
        paragraphs.append({
            "paragraph_id": para,
            "word_count": len(pw),
            "start_sec": pw[0]["start_sec"],
            "end_sec": pw[-1]["end_sec"],
        })
    lines: list[dict[str, Any]] = []
    for para in seen_paras:
        pw = [w for w in words if w["paragraph_id"] == para]
        cur: list[dict[str, Any]] = []
        for w in pw:
            trial = cur + [w]
            if cur and (len(trial) > _MAX_WORDS_PER_LINE or trial[-1]["end_sec"] - trial[0]["start_sec"] > _MAX_LINE_SEC + _TOL):
                lines.append({
                    "paragraph_id": para,
                    "text": " ".join(x["word"] for x in cur),
                    "start_sec": cur[0]["start_sec"],
                    "end_sec": cur[-1]["end_sec"],
                    "word_count": len(cur),
                })
                cur = [w]
            else:
                cur = trial
        if cur:
            lines.append({
                "paragraph_id": para,
                "text": " ".join(x["word"] for x in cur),
                "start_sec": cur[0]["start_sec"],
                "end_sec": cur[-1]["end_sec"],
                "word_count": len(cur),
            })
    return {
        "word_count": len(words),
        "first_start_sec": words[0]["start_sec"],
        "last_end_sec": words[-1]["end_sec"],
        "duration_sec": round(words[-1]["end_sec"] - words[0]["start_sec"], 3),
        "source_duration_sec": source_duration,
        "words": words,
        "paragraphs": paragraphs,
        "karaoke_lines": lines,
        "karaoke_line_count": len(lines),
        "timestamp_basis": "absolute source seconds",
        "contract_version": 1,
    }


def _render_contract(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_contract(params.get("transcript"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "word_subtitle_contract.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={
            "report_json": str(report),
            "word_count": result["word_count"],
            "karaoke_line_count": result["karaoke_line_count"],
        },
    )


def register_word_subtitle_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.word_subtitle_contract",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"transcript": {"type": "object"}},
            "required": ["transcript"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render_contract,
        has_media_output=False,
        description=(
            "Word-level subtitle contract (clean-room): absolute source "
            "timestamps, non-decreasing paragraph order, no overlap and "
            "no reorder, with deterministic karaoke lines derived from "
            "the contract. Bad transcripts raise, never silently repair."
        ),
        line="edit",
    ))
    return ["edit.word_subtitle_contract"]


register_word_subtitle_contract_capabilities_once()
