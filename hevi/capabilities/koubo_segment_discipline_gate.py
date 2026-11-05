"""Koubo segmentation discipline gate (``qa.koubo_segment_discipline_gate``).

Clean-room restatement of the cyber-xiaoya-live review (see
``CYBER_XIAOYA_ATTRIBUTION.md``): the upstream live system's
narration workbench splits a long text into segments, synthesizes
each segment separately and feeds the segments to the digital
human in order. Splitting must never break a URL, an email
address, a version number, a time, a decimal, a percentage or
an English word, and must never cut a sentence in half. The
segment audio goes to its own output, separate from the song
list. This gate judges claims about such segmentation only: the
seven protected token classes must all be declared, segments
must be ordered, sentences must stay whole, each segment must
be synthesized separately, feeding must be sequential, and the
separate output must be declared. This gate executes nothing:
``executed_here`` is always false, and real synthesis is a
separate TTS/GPU case.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PROTECTED_TOKENS: frozenset[str] = frozenset(
    {"url", "email", "version", "time", "decimal", "percent", "english_word"}
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_koubo_segment_discipline(claim: Any) -> dict[str, Any]:
    """Validate a claim about koubo long-text segmentation.

    Verdicts are ``pass`` / ``fail`` only. All seven protected
    token classes must be declared and no unknown class may be
    claimed; segments must be ordered, sentences must stay
    whole, each segment must be synthesized separately, feeding
    must be sequential, and the output must be declared
    separate from the song list.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail(
            "claim_not_object",
            "koubo segmentation claim must be a JSON object",
        )
    protected = claim.get("protected_tokens")
    if not isinstance(protected, list):
        return fail(
            "protected_tokens_missing",
            "koubo segmentation needs a protected-token list",
        )
    unknown = [token for token in protected if token not in PROTECTED_TOKENS]
    if unknown:
        return fail(
            "protected_token_unknown",
            f"unknown protected token class: {unknown[0]}",
        )
    missing = sorted(PROTECTED_TOKENS - set(protected))
    if missing:
        return fail(
            "protected_token_missing",
            f"protected token class missing: {missing[0]}",
        )
    if claim.get("segments_ordered") is not True:
        return fail(
            "segments_order_not_declared",
            "koubo segments must be declared ordered",
        )
    if claim.get("no_sentence_break") is not True:
        return fail(
            "sentence_break_rule_missing",
            "koubo segmentation must declare that sentences stay whole",
        )
    if claim.get("per_segment_tts") is not True:
        return fail(
            "per_segment_tts_missing",
            "koubo segmentation must declare per-segment synthesis",
        )
    if claim.get("feed_order") != "sequential":
        return fail(
            "feed_order_not_sequential",
            "koubo segments must be fed sequentially to the digital human",
        )
    if claim.get("declares_separate_output") is not True:
        return fail(
            "separate_output_not_declared",
            "koubo audio must be declared separate from the song list",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "protected_tokens": sorted(PROTECTED_TOKENS),
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_koubo_segment_discipline(params.get("claim"))
    report_path = out_dir / "koubo_segment_discipline_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_koubo_segment_discipline_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.koubo_segment_discipline_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Koubo segmentation discipline gate: long text is "
                "split without breaking URLs, emails, versions, "
                "times, decimals, percentages or English words, "
                "sentences stay whole, segments are synthesized "
                "separately and fed sequentially, audio stays "
                "separate from the song list."
            ),
        )
    )
    return ["qa.koubo_segment_discipline_gate"]


__all__ = [
    "PROTECTED_TOKENS",
    "check_koubo_segment_discipline",
    "register_koubo_segment_discipline_gate_capabilities_once",
]
