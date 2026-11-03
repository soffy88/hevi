"""Review-fusion gate (``qa.review_fusion_gate``).

Clean-room rewrite of the *method* in the rea-video field report
(``hevi-vs-rea-video.md`` section 2.1 item 3): a verdict on a
finished film fuses three parties -- the deterministic tool,
the looking reviewer, and (when present) a vision model -- and
the fusion must be declared, not improvised. The declared
caliber is a deterministic weight of 0.6 against the vision
model, two hard constraints that no fusion may break (a frozen
frame cannot be judged a video-generation class; a rigid whole
picture push/pull cannot be judged live action or a digital
human), and a disagreement rule (tool and reviewer disagree,
the shot goes on the must-watch list). A fusion record that
declares no weights, drops a hard constraint, or settles a
disagreement silently fails.

This gate judges fusion records only. It runs no vision model,
holds no key, and never copies any upstream model's verdict.
Shape: ``{"deterministic_weight": 0.6, "hard_constraints":
["frozen_frame_not_generated", "rigid_push_pull_not_live"],
"verdicts": [{"shot_id", "tool_label", "reviewer_label",
"final_label", "must_watch": bool}]}``.
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

DETERMINISTIC_WEIGHT = 0.6
REQUIRED_CONSTRAINTS = (
    "frozen_frame_not_generated",
    "rigid_push_pull_not_live",
)
GENERATED_CLASSES = ("ai_video", "digital_human")
LIVE_CLASSES = ("live_action", "digital_human")


def check_review_fusion(record: dict[str, Any] | None) -> dict[str, Any]:
    """Judge whether a fusion record declares its fusion honestly."""
    issues: list[str] = []
    if not isinstance(record, dict):
        raise CapabilityError("review-fusion record must be an object")
    weight = record.get("deterministic_weight")
    if weight is None:
        issues.append("weight_undeclared: deterministic_weight is required")
    elif not isinstance(weight, (int, float)) or isinstance(weight, bool):
        issues.append(f"bad_weight: deterministic_weight {weight!r} is not a number")
    elif abs(float(weight) - DETERMINISTIC_WEIGHT) > 1e-9:
        issues.append(
            f"weight_mismatch: deterministic_weight {weight} is not the "
            f"declared caliber {DETERMINISTIC_WEIGHT}"
        )
    constraints = record.get("hard_constraints")
    if not isinstance(constraints, list):
        issues.append("hard_constraints_not_list")
        constraints = []
    for required in REQUIRED_CONSTRAINTS:
        if required not in constraints:
            issues.append(f"missing_hard_constraint: {required}")
    verdicts = record.get("verdicts")
    if not isinstance(verdicts, list) or not verdicts:
        issues.append("missing_verdicts: fusion declares no per-shot verdicts")
        return {"verdict": "fail", "ok": False, "issues": issues}
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            issues.append("verdict_not_object")
            continue
        shot_id = verdict.get("shot_id")
        final = verdict.get("final_label")
        if verdict.get("frozen_frame") and final in GENERATED_CLASSES:
            issues.append(
                f"hard_constraint_broken: shot {shot_id!r} is a frozen "
                f"frame and cannot be judged {final!r}"
            )
        if verdict.get("rigid_push_pull") and final in LIVE_CLASSES:
            issues.append(
                f"hard_constraint_broken: shot {shot_id!r} is a rigid "
                f"whole-picture push/pull and cannot be judged {final!r}"
            )
        tool_label = verdict.get("tool_label")
        reviewer_label = verdict.get("reviewer_label")
        if (
            tool_label is not None
            and reviewer_label is not None
            and tool_label != reviewer_label
            and not verdict.get("must_watch")
        ):
            issues.append(
                f"disagreement_not_flagged: shot {shot_id!r} tool "
                f"{tool_label!r} vs reviewer {reviewer_label!r} without must_watch"
            )
    verdict = "fail" if issues else "pass"
    return {"verdict": verdict, "ok": not issues, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_review_fusion(params.get("record"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "review_fusion.json"
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


def register_review_fusion_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.review_fusion_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"record": {"type": "object"}},
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Review-fusion gate (rea-video A5, clean-room): "
                "declared 0.6 deterministic weight, two hard "
                "constraints, disagreements on the must-watch list. "
                "See REA_VIDEO_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.review_fusion_gate"]


register_review_fusion_gate_capabilities_once()
