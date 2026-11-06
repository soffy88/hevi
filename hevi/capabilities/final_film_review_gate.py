"""Final-film review gate (``qa.final_film_review_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): the finished film
is handed to a fresh reviewer as a first-time viewer, with
no conclusions attached. The reviewer writes down the story
as understood, lists what is unclear, checks every shot
for repeated moves, prop counts, continuity breaks, jumps,
colour shifts, warped faces and text problems, grades each
finding as a hard fault or a small problem, samples three
frames either side of every cut, and states plainly what
cannot be checked from stills — the feel of the motion and
the sound. This gate formalises the standing hevi rule of
a full-film ASR listen-through plus dense frame review. It
judges the review record only. It renders nothing and
spends nothing: ``executed_here`` is always false.
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

SEVERITIES: frozenset[str] = frozenset({"hard", "minor"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_final_film_review(review: Any) -> dict[str, Any]:
    """Validate a final-film review record.

    Verdicts are ``pass`` / ``fail`` only. A review fails
    when it names no film, when it has no verdict, when a
    finding carries an ungraded severity, when it does not
    state what cannot be checked from stills, when cut
    frames were not sampled, or when a hard fault stands
    under a pass verdict.
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
    film = review.get("film_file")
    if not isinstance(film, str) or not film.strip():
        return fail("film_missing", "review must name the finished film file")
    if not isinstance(review.get("story_understood"), str):
        return fail(
            "story_understood_missing",
            "reviewer must write down the story as understood",
        )
    if not isinstance(review.get("unclear_points"), list):
        return fail(
            "unclear_points_missing",
            "review must list what is unclear, even when the list is empty",
        )
    uncheckable = review.get("uncheckable")
    if not isinstance(uncheckable, list) or not uncheckable:
        return fail(
            "uncheckable_not_declared",
            "review must state what cannot be checked from stills, "
            "such as the feel of the motion and the sound",
        )
    if review.get("cut_frames_checked") is not True:
        return fail(
            "cut_frames_not_checked",
            "review must sample three frames either side of every cut",
        )
    findings = review.get("findings")
    if not isinstance(findings, list):
        return fail(
            "findings_missing",
            "review must carry a findings list, even when empty",
        )
    hard_count = 0
    for position, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return fail(
                "finding_not_object",
                f"finding {position} must be an object",
            )
        severity = finding.get("severity")
        if severity not in SEVERITIES:
            return fail(
                "severity_ungraded",
                f"finding {position} must be graded hard or minor",
            )
        if severity == "hard":
            hard_count += 1
        if not isinstance(finding.get("time_s"), (int, float)):
            return fail(
                "finding_time_missing",
                f"finding {position} must carry its time in seconds",
            )
    verdict = review.get("verdict")
    if verdict not in ("pass", "fail"):
        return fail(
            "verdict_missing",
            "review must end with a two-valued verdict: pass or fail",
        )
    if verdict == "pass" and hard_count > 0:
        return fail(
            "hard_issues_unresolved",
            f"{hard_count} hard fault(s) stand under a pass verdict",
        )
    if verdict != "pass":
        return fail(
            "review_not_passed",
            "the film does not pass final review",
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
    report = check_final_film_review(params.get("review"))
    report_path = out_dir / "final_film_review_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_final_film_review_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.final_film_review_gate",
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
                "Final-film review gate: first-time viewer, story as "
                "understood, findings graded hard or minor, three "
                "frames either side of every cut, uncheckable motion "
                "feel and sound stated plainly."
            ),
        )
    )
    return ["qa.final_film_review_gate"]


__all__ = [
    "SEVERITIES",
    "check_final_film_review",
    "register_final_film_review_gate_capabilities_once",
]
