"""Misread judgement gate (``qa.misread_judgement_gate``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item A3: whether a line was misread is judged by comparing the
script against the transcription word by word. A transcription
produced with the script supplied as a prompt is not pronunciation
evidence at all: a recogniser handed the expected words will
return the expected words, so such a transcript can never prove
a line was read correctly or incorrectly.

Every difference between script and transcript must carry a
judgement, and every judgement must be classified into exactly
one of three classes:

* ``true_misread`` -- the speaker really said it wrong;
* ``transcription_error`` -- the speaker said it right and the
  recogniser wrote it wrong;
* ``unconfirmed`` -- the evidence does not settle it, and no
  repair may be ordered on it.

An unclassified judgement fails. A judgement with no stated
basis fails, except ``unconfirmed``, whose basis is precisely
that the evidence does not settle it. A ``transcription_error``
claim on a word the transcript already matches fails: there is
no transcription difference for the claim to explain (a matching
word claimed misread is the homophone case and must be judged
``true_misread`` with a basis, not ``transcription_error``).

This module judges judgement records only. It never transcribes,
never re-records, and never repairs a misreading; repair is a
separate, blocked item (it needs a real voice and a real key).
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

JUDGEMENT_CLASSES = ("true_misread", "transcription_error", "unconfirmed")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.misread_judgement_gate: {detail}"}
    issue.update(extra)
    return issue


def _word_list(value: Any, field: str) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(w, str) and w.strip() for w in value):
        return None
    return value


def check_misread_judgement(record: Any) -> dict[str, Any]:
    """Judge one misread judgement record. Returns a report; never raises."""
    issues: list[dict[str, Any]] = []
    if not isinstance(record, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("record_not_object", "judgement record must be an object")],
        }
    script_words = _word_list(record.get("script_words"), "script_words")
    transcript_words = _word_list(record.get("transcript_words"), "transcript_words")
    if script_words is None:
        issues.append(_issue(
            "script_words_invalid",
            "script_words must be a non-empty list of non-empty strings",
        ))
    if transcript_words is None:
        issues.append(_issue(
            "transcript_words_invalid",
            "transcript_words must be a non-empty list of non-empty strings",
        ))
    if script_words is None or transcript_words is None:
        return {"ok": False, "verdict": "fail", "issues": issues}

    if record.get("prompt_included_script") is True:
        issues.append(_issue(
            "prompted_transcript_not_pronunciation_evidence",
            "the transcript was produced with the script supplied as a "
            "prompt; it cannot serve as pronunciation evidence and the "
            "record must be re-transcribed without the script prompt",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    if "prompt_included_script" not in record:
        issues.append(_issue(
            "prompt_disclosure_missing",
            "the record must state whether the transcript prompt "
            "included the script (prompt_included_script)",
        ))

    compared = max(len(script_words), len(transcript_words))
    differing: list[int] = []
    for index in range(compared):
        script_word = script_words[index] if index < len(script_words) else None
        transcript_word = (
            transcript_words[index] if index < len(transcript_words) else None
        )
        if script_word != transcript_word:
            differing.append(index)

    judgements = record.get("judgements")
    if not isinstance(judgements, list):
        issues.append(_issue(
            "judgements_missing",
            "judgements must be a list (possibly empty when script and "
            "transcript agree word for word)",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    judged_indices: set[int] = set()
    for position, judgement in enumerate(judgements):
        if not isinstance(judgement, dict):
            issues.append(_issue(
                "judgement_invalid",
                f"judgement {position} must be an object",
            ))
            continue
        index = judgement.get("word_index")
        if not isinstance(index, int) or isinstance(index, bool) \
                or not 0 <= index < len(script_words):
            issues.append(_issue(
                "judgement_index_invalid",
                f"judgement {position} word_index must be within the script",
            ))
            continue
        judged_indices.add(index)
        classification = judgement.get("classification")
        if classification not in JUDGEMENT_CLASSES:
            issues.append(_issue(
                "judgement_unclassified",
                f"judgement at word {index} must be classified as one of "
                f"{', '.join(JUDGEMENT_CLASSES)}; an unclassified "
                "judgement fails",
                word_index=index,
            ))
            continue
        if classification in ("true_misread", "transcription_error"):
            if not isinstance(judgement.get("basis"), str) \
                    or not judgement["basis"].strip():
                issues.append(_issue(
                    "judgement_basis_missing",
                    f"a {classification} judgement at word {index} must "
                    "state its basis",
                    word_index=index,
                ))
        if classification == "transcription_error" and index not in differing:
            issues.append(_issue(
                "transcription_error_without_difference",
                f"word {index} matches the transcript, so there is no "
                "transcription difference for a transcription_error "
                "claim to explain",
                word_index=index,
            ))
    for index in differing:
        if index not in judged_indices:
            issues.append(_issue(
                "difference_without_judgement",
                f"script/transcript difference at word {index} "
                f"({script_words[index]!r} vs "
                f"{transcript_words[index] if index < len(transcript_words) else None!r}) "
                "carries no judgement",
                word_index=index,
            ))
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "differing_word_indices": differing,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_misread_judgement(params.get("record"))
    report_path = Path(out_dir) / "misread_judgement_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_misread_judgement_gate_capabilities_once() -> list[str]:
    """Register ``qa.misread_judgement_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.misread_judgement_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Misread judgement gate: misreading is judged by "
                "word-by-word script/transcript comparison; a "
                "transcript prompted with the script is not "
                "pronunciation evidence; every judgement is classified "
                "true_misread, transcription_error, or unconfirmed. "
                "Judges records only."
            ),
            line="qa",
        )
    )
    return ["qa.misread_judgement_gate"]


register_misread_judgement_gate_capabilities_once()
