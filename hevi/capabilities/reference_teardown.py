"""Reference teardown and transcript structuring (``research.reference_teardown``).

This module studies a reference so a new work can be planned --
it never supplies material to copy. Its standing declaration, which
appears in every report, is: teardown only; the reference's footage,
wording, and expression must not be reused, and every element of
the new work -- its material, its examples, its wording -- must be
the creator's own.

Four questions are answered from evidence in the supplied source,
never invented:

1. Hook: what opens the piece (first sentence or paragraph).
2. Pain point: the problem the audience is shown to have.
3. Information gain: the one new fact, number, or method the
   audience walks away with.
4. Closing hook: what pulls the audience to the next piece.

Where the source contains no evidence for a question, the answer
is "not found in the supplied source", with no evidence quote --
a gap is reported as a gap, not filled with a guess.

Title candidates are reviewed one by one for risk: absolute or
guarantee claims, claims whose numbers do not appear in the source,
and titles so long they will not fit a cover. A transcript, when
supplied, is structured into hook / body / closing entries with
any timestamps it already carries; timestamps are never invented.

Fetching is deliberately separated from analysis: the caller
supplies a fetcher callable, or no fetcher at all. With no fetcher,
or when the fetcher fails, the report lists the missing backend
and stops -- it never fabricates a reference to analyse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

ORIGINALITY_DECLARATION = (
    "Teardown only: this analysis studies structure, it does not "
    "transfer material. Do not reuse the reference's footage, "
    "wording, examples, or expression. Every element of the new work "
    "-- its material, its examples, its wording -- must be original "
    "to the creator."
)

_PAIN_MARKERS = ("痛点", "难题", "问题是", "困扰", "失败", "怕", "太贵",
                 "太慢", "做不好", "学不会", "一直")
_GAIN_MARKERS = ("原来", "其实", "关键是", "方法是", "秘诀", "记住",
                 "只需要", "只要")
_CLOSE_MARKERS = ("下期", "关注", "留言", "怎么办", "下集", "点赞", "?",
                  "？")
_ABSOLUTE_RE = re.compile(r"保证|一定|绝对|100%|包赚|稳赚|月入十万|暴富")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\n]+")
_TIMESTAMP_RE = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*")


def _sentences(text: str) -> list[str]:
    return [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


def _first_with(sentences: list[str], markers: tuple[str, ...]) -> str | None:
    for sentence in sentences:
        if any(m in sentence for m in markers):
            return sentence
    return None


def _first_with_number(sentences: list[str]) -> str | None:
    for sentence in sentences:
        if _NUMBER_RE.search(sentence) or any(
                m in sentence for m in _GAIN_MARKERS):
            return sentence
    return None


def fetch_reference(
    url: str,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Fetch a reference, or report the missing backend honestly.

    No default network backend is built in: without a caller-supplied
    fetcher there is nothing to fetch with, and the report says so
    instead of inventing content.
    """
    if not url or not isinstance(url, str):
        raise CapabilityError(
            "research.reference_teardown: url must be a non-empty string"
        )
    if fetcher is None:
        return {
            "ok": False,
            "url": url,
            "content": None,
            "missing_backends": [
                "no fetcher/backend was supplied to fetch_reference; "
                "pass a fetcher callable (for example a browser or "
                "platform reader) -- the module ships none, so a "
                "missing fetcher is a gap, not a silent failure",
            ],
            "analysis": None,
        }
    try:
        content = fetcher(url)
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "content": None,
            "missing_backends": [
                f"fetcher failed for {url}: {exc}; no content was "
                "retrieved and no analysis was fabricated from it",
            ],
            "analysis": None,
        }
    if not content or not str(content).strip():
        return {
            "ok": False,
            "url": url,
            "content": None,
            "missing_backends": [
                "fetcher returned empty content; nothing was analysed",
            ],
            "analysis": None,
        }
    return {"ok": True, "url": url, "content": str(content),
            "missing_backends": [], "analysis": None}


def teardown_reference(
    text: Any,
    *,
    title_candidates: Any = None,
) -> dict[str, Any]:
    """Answer the four teardown questions from the supplied text only."""
    if not isinstance(text, str) or not text.strip():
        raise CapabilityError(
            "research.reference_teardown: source text must be non-empty; "
            "a teardown with no source would have to invent its answers"
        )
    sentences = _sentences(text)
    hook = sentences[0] if sentences else None
    pain = _first_with(sentences, _PAIN_MARKERS)
    gain = _first_with_number(sentences)
    closing = sentences[-1] if sentences else None
    closing_is_hook = bool(
        closing and any(m in closing for m in _CLOSE_MARKERS))

    def answer(value: str | None, note: str) -> dict[str, Any]:
        return {
            "found": value is not None,
            "evidence": value,
            "note": note if value is None else "quoted from the source",
        }

    report: dict[str, Any] = {
        "originality_declaration": ORIGINALITY_DECLARATION,
        "questions": {
            "hook": answer(hook, "not found in the supplied source"),
            "pain_point": answer(
                pain, "not found in the supplied source: no problem "
                      "statement was identified in the text"),
            "information_gain": answer(
                gain, "not found in the supplied source: no new fact, "
                      "number, or method was identified in the text"),
            "closing_hook": {
                "found": closing is not None,
                "evidence": closing,
                "is_hook": closing_is_hook,
                "note": ("quoted from the source; flagged as a weak "
                         "closing when it contains no next-step, "
                         "question, or follow marker")
                if closing and not closing_is_hook
                else "quoted from the source",
            },
        },
        "source_sentence_count": len(sentences),
    }
    candidates = title_candidates or []
    if not isinstance(candidates, list):
        raise CapabilityError(
            "research.reference_teardown: title_candidates must be a list"
        )
    report["title_reviews"] = [
        review_title_candidate(candidate, text) for candidate in candidates
    ]
    return report


def review_title_candidate(candidate: Any, source_text: str) -> dict[str, Any]:
    """Review one title candidate for risk, against the source."""
    if not isinstance(candidate, str) or not candidate.strip():
        raise CapabilityError(
            "research.reference_teardown: title candidate must be "
            "non-empty text"
        )
    risks: list[str] = []
    if _ABSOLUTE_RE.search(candidate):
        risks.append(
            "absolute/guarantee claim: words such as 保证 / 一定 / 100% "
            "promise an outcome the piece cannot guarantee; soften or "
            "prove the claim, or drop it"
        )
    for number in _NUMBER_RE.findall(candidate):
        if number and number not in source_text:
            risks.append(
                f"claim not in source: the number '{number}' does not "
                "appear in the reference, so the title promises more "
                "than the piece contains"
            )
    if len(candidate) > 20:
        risks.append(
            "overlong title: longer than 20 characters, likely to be "
            "cut off on a cover; shorten to the one point that matters"
        )
    return {
        "candidate": candidate,
        "risks": risks,
        "verdict": "risky" if risks else "ok",
    }


def structure_transcript(transcript: Any) -> dict[str, Any]:
    """Structure a transcript into hook / body / closing entries.

    Timestamps are kept only when the transcript already carries
    them; none are invented for lines that have none.
    """
    if not isinstance(transcript, str) or not transcript.strip():
        raise CapabilityError(
            "research.reference_teardown: transcript must be non-empty text"
        )
    entries: list[dict[str, Any]] = []
    for line in transcript.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _TIMESTAMP_RE.match(line)
        entries.append({
            "timestamp": match.group(1) if match else None,
            "text": _TIMESTAMP_RE.sub("", line).strip() if match else line,
        })
    if not entries:
        raise CapabilityError(
            "research.reference_teardown: transcript has no usable lines"
        )
    return {
        "entries": entries,
        "sections": {
            "hook": entries[0],
            "body": entries[1:-1] if len(entries) > 2 else [],
            "closing": entries[-1] if len(entries) > 1 else None,
        },
        "note": "Structural split only: hook is the first entry, "
                "closing the last, body everything between. Timestamps "
                "shown are only those the transcript already carried.",
    }


def teardown_with_transcript(
    text: Any,
    *,
    title_candidates: Any = None,
    transcript: Any = None,
) -> dict[str, Any]:
    """Teardown plus, when supplied, a structured transcript."""
    report = teardown_reference(text, title_candidates=title_candidates)
    if transcript is not None:
        report["transcript"] = structure_transcript(transcript)
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = teardown_with_transcript(
        params.get("source_text"),
        title_candidates=params.get("title_candidates") or [],
        transcript=params.get("transcript"),
    )
    report_path = out_dir / "reference_teardown_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path),
            "title_reviews": len(report["title_reviews"])},
    )


def register_reference_teardown_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="research.reference_teardown",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "source_text": {"type": "string"},
                    "title_candidates": {"type": "array",
                                         "items": {"type": "string"}},
                    "transcript": {"type": "string"},
                },
                "required": ["source_text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Reference teardown: hook, pain point, information gain, "
                "and closing hook answered only from quoted source "
                "evidence (gaps reported as gaps), each title candidate "
                "reviewed for guarantee, off-source, and overlong risks, "
                "and an optional transcript structured into hook/body/"
                "closing. Teardown only: no reference material or "
                "wording is reused, and a failed fetch lists its missing "
                "backend instead of fabricating content."
            ),
            line="research",
            has_media_output=False,
        )
    )
    return ["research.reference_teardown"]


register_reference_teardown_capabilities_once()
