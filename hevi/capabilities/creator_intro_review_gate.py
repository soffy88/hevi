"""Creator intro review gate (``qa.creator_intro_review_gate``).

Clean-room restatement of the ChrisHKAI-Video creator-intro
method (see ``CHRISHKAI_VIDEO_ATTRIBUTION.md``): the finished
film is reviewed blind — the reviewer receives only the film
and the brief, never any conclusions — and each round fixes
at most the top three issues, for at most two rounds. The
review ends with a two-valued verdict: pass or fail.
This gate complements ``qa.blind_review_gate`` (Eian
workflow), which checks the pre-submit review of prompt and
pictures; this gate checks the finished-film review loop.
It judges the review record only and edits nothing:
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

MAX_ROUNDS = 2
MAX_FIXES_PER_ROUND = 3


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_creator_intro_review(review: Any) -> dict[str, Any]:
    """Validate a creator-intro finished-film review record.

    Pass requires the reviewer to have received the film and
    the brief only, at most two rounds, at most three fixes
    per round, and a pass verdict with no open findings.
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
    if review.get("film_given") is not True:
        return fail(
            "film_missing",
            "the reviewer must be given the finished film",
        )
    if review.get("brief_given") is not True:
        return fail(
            "brief_missing",
            "the reviewer must be given the brief",
        )
    if review.get("conclusions_given") is True:
        return fail(
            "conclusions_given",
            "the reviewer receives the film and the brief only, never conclusions",
        )
    rounds = review.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        return fail(
            "rounds_missing",
            "review must list its rounds",
        )
    if len(rounds) > MAX_ROUNDS:
        return fail(
            "too_many_rounds",
            f"review ran {len(rounds)} rounds; at most two rounds are allowed",
        )
    for index, round_ in enumerate(rounds):
        if not isinstance(round_, dict):
            return fail(
                "round_not_object",
                f"round {index} must be a JSON object",
            )
        fixes = round_.get("issues_fixed")
        if not isinstance(fixes, list):
            return fail(
                "fixes_missing",
                f"round {index} must list the issues it fixed",
            )
        if len(fixes) > MAX_FIXES_PER_ROUND:
            return fail(
                "too_many_fixes",
                f"round {index} fixed {len(fixes)} issues; at most the top three per round",
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
            "nothing ships without a reviewer pass",
        )
    findings = review.get("open_findings")
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
    report = check_creator_intro_review(params.get("review"))
    report_path = out_dir / "creator_intro_review_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_creator_intro_review_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.creator_intro_review_gate",
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
                "Creator intro review gate: finished film reviewed "
                "blind from film plus brief only, at most two rounds, "
                "at most the top three fixes per round, pass or fail. "
                "Complements qa.blind_review_gate."
            ),
        )
    )
    return ["qa.creator_intro_review_gate"]


__all__ = [
    "MAX_FIXES_PER_ROUND",
    "MAX_ROUNDS",
    "check_creator_intro_review",
    "register_creator_intro_review_gate_capabilities_once",
]
