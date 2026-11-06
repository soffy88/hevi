"""Pre-submit blind review gate (``qa.blind_review_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): before a shot
is submitted for paid generation, a fresh reviewer who
has seen nothing else checks the prompt and the pictures.
The reviewer only finds faults and never edits a file,
receives the materials only and no conclusions, and ends
with a two-valued verdict: pass or fail. Nothing is
submitted without a pass. This gate judges the review
record only. It generates no video and spends nothing:
``executed_here`` is always false.
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

# The reviewer must receive all six, and nothing else.
REQUIRED_MATERIALS: tuple[str, ...] = (
    "prompt_file",
    "first_frame",
    "last_frame",
    "setting_sheet",
    "shotlist",
    "palette_rules",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_blind_review(review: Any) -> dict[str, Any]:
    """Validate a pre-submit blind review record.

    Verdicts are ``pass`` / ``fail`` only. A review fails
    when the reviewer edited a file, when conclusions were
    handed to the reviewer, when a required material is
    missing, when the verdict is not a two-valued pass or
    fail, or when the verdict is not a pass.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(review, dict):
        return fail("review_not_object", "review must be a JSON object")
    if review.get("files_modified") is True:
        return fail(
            "reviewer_modified_files",
            "the reviewer only finds faults and never edits a file",
        )
    if review.get("conclusions_given") is True:
        return fail(
            "conclusions_given",
            "the reviewer receives the materials only, never conclusions",
        )
    materials = review.get("materials")
    if not isinstance(materials, dict):
        return fail(
            "materials_missing",
            "review must list the materials handed to the reviewer",
        )
    for name in REQUIRED_MATERIALS:
        if not materials.get(name):
            return fail(
                "materials_incomplete",
                f"review materials are missing {name}",
            )
    verdict = review.get("verdict")
    if verdict not in ("pass", "fail"):
        return fail(
            "verdict_missing",
            "review must end with a two-valued verdict: pass or fail",
        )
    if verdict != "pass":
        return fail(
            "review_not_passed",
            "nothing is submitted without a reviewer pass",
        )
    findings = review.get("findings")
    if isinstance(findings, list) and findings:
        return fail(
            "inconsistent_verdict",
            "a pass verdict cannot carry open findings",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_blind_review(params.get("review"))
    report_path = out_dir / "blind_review_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_blind_review_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.blind_review_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "review": {"type": "object"},
                },
                "required": ["review"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pre-submit blind review gate: reviewer only finds "
                "faults, never edits a file, receives materials only "
                "with no conclusions, and ends with pass or fail."
            ),
        )
    )
    return ["qa.blind_review_gate"]


__all__ = [
    "REQUIRED_MATERIALS",
    "check_blind_review",
    "register_blind_review_gate_capabilities_once",
]
