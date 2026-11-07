"""Per-segment listen-back gate (``qa.segment_listenback_gate``).

Clean-room rewrite of the discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item A2: every segment must carry a listen-back record before it
may enter assembly. A segment with no listen-back record is not
assembled, and a segment whose record is incomplete is not
assembled either.

A listen-back record follows the ``audio.asr_transcribe`` evidence
shape: the transcript, the traditional-to-simplified (t2s)
normalised transcript, a coverage figure, the model name, the
normalisation backend, and the audited-glossary version. The
normalisation backend must be one that actually normalises
(``builtin`` or ``opencc``): ``none`` is an explicit opt-out and
does not count as a listen-back, and a record without the audited
glossary version in force (``asr-glossary-v1``) is stale and must
be re-run.

No coverage threshold is set here. Reported coverage figures from
another author are not adopted as defaults; coverage is recorded
and must simply be a number in [0, 1]. This module judges records
only. It never transcribes, never calls a model, and never
assembles anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.asr_glossary import GLOSSARY_VERSION
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Evidence fields a listen-back record must carry, mirroring the
# audio.asr_transcribe evidence shape.
LISTENBACK_EVIDENCE_FIELDS = (
    "transcript",
    "transcript_t2s",
    "coverage",
    "model_name",
    "normalization",
    "glossary_version",
)

_NORMALISING_BACKENDS = ("builtin", "opencc")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.segment_listenback_gate: {detail}"}
    issue.update(extra)
    return issue


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_listenback(record: Any, segment_id: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if record is None:
        return [_issue(
            "listenback_missing",
            f"segment {segment_id!r} has no listen-back record",
            segment_id=segment_id,
        )]
    if not isinstance(record, dict):
        return [_issue(
            "listenback_invalid",
            f"segment {segment_id!r} listen-back record must be an object",
            segment_id=segment_id,
        )]
    for field in ("transcript", "transcript_t2s"):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            issues.append(_issue(
                "listenback_field_missing",
                f"segment {segment_id!r} listen-back record needs a "
                f"non-empty {field}",
                segment_id=segment_id,
                field=field,
            ))
    coverage = record.get("coverage")
    if not _is_number(coverage) or not 0.0 <= float(coverage) <= 1.0:
        issues.append(_issue(
            "coverage_invalid",
            f"segment {segment_id!r} coverage must be a number in [0, 1]",
            segment_id=segment_id,
        ))
    if not isinstance(record.get("model_name"), str) \
            or not record["model_name"].strip():
        issues.append(_issue(
            "model_name_missing",
            f"segment {segment_id!r} listen-back record must name the model",
            segment_id=segment_id,
        ))
    if record.get("normalization") not in _NORMALISING_BACKENDS:
        issues.append(_issue(
            "normalization_not_applied",
            f"segment {segment_id!r} listen-back must use a normalising "
            "backend (builtin or opencc) with the audited glossary; "
            "'none' does not count",
            segment_id=segment_id,
        ))
    if record.get("glossary_version") != GLOSSARY_VERSION:
        issues.append(_issue(
            "glossary_version_stale",
            f"segment {segment_id!r} glossary_version must be the "
            f"audited glossary in force ({GLOSSARY_VERSION})",
            segment_id=segment_id,
        ))
    return issues


def check_segment_listenback(plan: Any) -> dict[str, Any]:
    """Judge one assembly plan. Returns a report; never raises for a bad plan."""
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "assembly_blocked": True,
            "segments": [],
            "issues": [_issue("plan_not_object", "assembly plan must be an object")],
        }
    segments = plan.get("segments")
    issues: list[dict[str, Any]] = []
    per_segment: list[dict[str, Any]] = []
    if not isinstance(segments, list) or not segments:
        issues.append(_issue(
            "segments_missing",
            "segments must be a non-empty list",
        ))
        return {
            "ok": False,
            "verdict": "fail",
            "assembly_blocked": True,
            "segments": per_segment,
            "issues": issues,
        }
    for entry in segments:
        if not isinstance(entry, dict):
            issues.append(_issue(
                "segment_invalid", "each segment must be an object",
            ))
            per_segment.append({"segment_id": None, "verdict": "fail"})
            continue
        segment_id = entry.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id.strip():
            issues.append(_issue(
                "segment_id_missing",
                "each segment must carry a non-empty segment_id",
            ))
            per_segment.append({"segment_id": segment_id, "verdict": "fail"})
            continue
        seg_issues = _check_listenback(entry.get("listenback"), segment_id)
        issues.extend(seg_issues)
        per_segment.append({
            "segment_id": segment_id,
            "verdict": "pass" if not seg_issues else "fail",
            "issues": seg_issues,
        })
    blocked = bool(issues) and plan.get("assembly_requested") is True
    if blocked:
        issues.append(_issue(
            "assembly_without_listenback",
            "assembly is refused: one or more segments have no valid "
            "listen-back record",
        ))
    verdict = "pass" if not issues else "fail"
    return {
        "ok": not issues,
        "verdict": verdict,
        "assembly_blocked": blocked,
        "segments": per_segment,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    report = check_segment_listenback(params.get("plan"))
    report_path = Path(out_dir) / "segment_listenback_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_segment_listenback_gate_capabilities_once() -> list[str]:
    """Register ``qa.segment_listenback_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.segment_listenback_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Per-segment listen-back gate: every segment needs an "
                "audio.asr_transcribe-shaped listen-back record "
                "(transcript, t2s transcript, coverage, model name, "
                "normalising backend, audited glossary version) before "
                "assembly. Judges records only."
            ),
            line="qa",
        )
    )
    return ["qa.segment_listenback_gate"]


register_segment_listenback_gate_capabilities_once()
