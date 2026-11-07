"""Evidence-priority gate (``qa.evidence_priority_gate``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.1 items 1 and 3): when a
finished film is reverse-engineered, hard evidence outranks
appearance. An AIGC marker, a frame-rate fingerprint, or a frozen
frame beats "it looks like" every time. When the deterministic
tool and the looking reviewer disagree, the shot goes on a
must-watch list -- the disagreement is never silently resolved
by taking the higher score. And a reviewer who never saw the
pictures may not overturn the tool's production-method
judgement: no pictures, no override.

This gate judges review records. ``review`` shape:
``{"shots": [{"id", "tool_label", "reviewer_label",
"hard_evidence": {"kind", "supports"}, "reviewer_saw_images": bool,
"must_watch": bool}], ...}``. ``hard_evidence.supports`` names
the label the hard evidence supports. A reviewer label that
contradicts supporting hard evidence fails; a disagreement
without ``must_watch`` fails; an override by a reviewer who did
not see the images fails. It calls no model and holds no key.
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

HARD_EVIDENCE_KINDS = (
    "aigc_marker",
    "frame_rate_fingerprint",
    "frozen_frame",
)


def check_evidence_priority(review: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether a review record honours the evidence order."""
    issues: list[str] = []
    if not isinstance(review, dict):
        raise CapabilityError("evidence-priority review must be an object")
    shots = review.get("shots")
    if not isinstance(shots, list) or not shots:
        issues.append("missing_shots: review declares no shots")
        return {"verdict": "fail", "ok": False, "issues": issues}
    for shot in shots:
        if not isinstance(shot, dict):
            issues.append("shot_not_object")
            continue
        shot_id = shot.get("id")
        tool_label = shot.get("tool_label")
        reviewer_label = shot.get("reviewer_label")
        hard = shot.get("hard_evidence")
        saw_images = shot.get("reviewer_saw_images")
        if hard is not None:
            if not isinstance(hard, dict) or hard.get("kind") not in HARD_EVIDENCE_KINDS:
                issues.append(f"bad_hard_evidence: shot {shot_id!r}")
            elif hard.get("supports") is not None and reviewer_label is not None:
                if reviewer_label != hard["supports"]:
                    issues.append(
                        f"hard_evidence_overruled: shot {shot_id!r} reviewer "
                        f"label {reviewer_label!r} contradicts hard evidence "
                        f"supporting {hard['supports']!r}"
                    )
        if tool_label is not None and reviewer_label is not None:
            if tool_label != reviewer_label:
                if not shot.get("must_watch"):
                    issues.append(
                        f"disagreement_not_flagged: shot {shot_id!r} tool "
                        f"{tool_label!r} vs reviewer {reviewer_label!r} "
                        "without must_watch"
                    )
                if saw_images is False:
                    issues.append(
                        f"blind_override: shot {shot_id!r} reviewer did not "
                        "see the images and may not overturn the tool judgement"
                    )
        if saw_images not in (True, False):
            issues.append(f"reviewer_saw_images_undeclared: shot {shot_id!r}")
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_evidence_priority(params.get("review"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "evidence_priority.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
        },
    )


_Registered = False


def register_evidence_priority_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.evidence_priority_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"review": {"type": "object"}},
                "required": ["review"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Evidence-priority gate (rea-video A2, clean-room): "
                "hard evidence outranks appearance; disagreements go "
                "on the must-watch list; a reviewer who never saw the "
                "images may not overturn the tool. See "
                "REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.evidence_priority_gate"]


register_evidence_priority_gate_capabilities_once()
