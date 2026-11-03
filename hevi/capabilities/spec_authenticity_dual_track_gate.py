"""Specification/authenticity dual-track gate (``qa.spec_authenticity_dual_track_gate``).

Clean-room restatement of the two-track review discipline
described in the batch-video-plugin review (see
``BATCH_VIDEO_PLUGIN_ATTRIBUTION.md``): a take is judged on
two separate tracks -- conformance to the declared
specification (duration, resolution, audio) and perceptual
authenticity (freedom from synthetic-looking artefacts).
Passing the specification track never implies passing the
authenticity track, and a single combined verdict must never
hide a failed track.

This module judges review reports only. It never inspects
pixels, never runs a model, and never touches a budget.
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

_VERDICTS = ("pass", "warn", "fail")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.spec_authenticity_dual_track_gate: {detail}"}
    issue.update(extra)
    return issue


def check_spec_authenticity(report: Any) -> dict[str, Any]:
    """Judge one review report on the two-track discipline.

    ``report`` carries ``spec_verdict`` and
    ``authenticity_verdict`` (each ``pass``/``warn``/``fail``),
    optional ``spec_evidence`` / ``authenticity_evidence``, and an
    optional caller-declared ``overall_verdict``. Verdict
    ``pass`` means both tracks are present and evidenced, and
    no caller-declared overall verdict claims a pass while a
    track has failed. The combined verdict is ``fail`` when
    either track fails, ``warn`` when neither fails but one
    warns, and ``pass`` only when both pass.
    """
    if not isinstance(report, dict):
        raise CapabilityError("review report must be an object")
    issues: list[dict[str, Any]] = []
    spec = report.get("spec_verdict")
    authenticity = report.get("authenticity_verdict")
    if spec not in _VERDICTS:
        issues.append(
            _issue("spec_verdict_missing", "spec_verdict must be one of pass/warn/fail")
        )
        spec = None
    if authenticity not in _VERDICTS:
        issues.append(
            _issue(
                "authenticity_missing",
                "authenticity_verdict must be one of pass/warn/fail and "
                "must never be silently merged into the spec verdict",
            )
        )
        authenticity = None
    if spec == "pass" and not report.get("spec_evidence"):
        issues.append(
            _issue("spec_evidence_missing", "a passing spec verdict requires spec_evidence")
        )
    if authenticity in ("pass", "warn") and not report.get("authenticity_evidence"):
        issues.append(
            _issue(
                "authenticity_evidence_missing",
                "a non-failing authenticity verdict requires authenticity_evidence",
            )
        )
    if spec == "fail" or authenticity == "fail":
        combined = "fail"
    elif spec == "warn" or authenticity == "warn":
        combined = "warn"
    elif spec == "pass" and authenticity == "pass":
        combined = "pass"
    else:
        combined = "fail"
    overall = report.get("overall_verdict")
    if overall is not None and overall != combined:
        issues.append(
            _issue(
                "verdict_conflation",
                f"caller overall_verdict {overall!r} hides combined verdict {combined!r}",
            )
        )
    verdict = "fail" if issues or combined == "fail" else combined
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "combined_verdict": combined,
        "spec_verdict": spec,
        "authenticity_verdict": authenticity,
        "issues": issues,
        "not_checked": [],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_spec_authenticity(params.get("report"))
    report_path = out_dir / "spec_authenticity.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_spec_authenticity_dual_track_gate_capabilities_once() -> list[str]:
    """Register ``qa.spec_authenticity_dual_track_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.spec_authenticity_dual_track_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                },
                "required": ["report"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Dual-track review gate: specification conformance and "
                "perceptual authenticity are judged separately, and a "
                "passing spec verdict never implies authenticity."
            ),
        )
    )
    return ["qa.spec_authenticity_dual_track_gate"]


__all__ = [
    "check_spec_authenticity",
    "register_spec_authenticity_dual_track_gate_capabilities_once",
]
