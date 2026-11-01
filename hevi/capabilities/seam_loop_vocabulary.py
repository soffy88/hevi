"""Seam and loop scoring vocabulary (``qa.seam_loop_vocabulary``).

Clean-room rewrite of the *scoring vocabulary* described in
``hevi-vs-open-3d-skills.md`` sections 2.2 and 2.3 (scroll-film
seams, motion-assets loop repair): seam scores are classified
against caller-supplied thresholds, and a loop is judged by a
caller-supplied jump value. This module judges *scores* only; it
measures no frames and calls no model.

Threshold discipline: every threshold is supplied by the caller
in the input. There are no defaults in this module -- no
invisible/jump seam numbers and no loop jump number are baked
in, and no author-reported number is used as a threshold. When
thresholds or scores are missing, the verdict is ``not_checked``
-- never a pass -- because an unmeasured seam or loop proves
nothing. ``not_checked`` is a real verdict with ``ok`` false.

Classification: a seam score at or below the caller-supplied
invisible maximum is ``invisible``; above the caller-supplied
jump minimum it is ``jump``; between the two it is ``visible``.
The gate passes only when every seam is invisible and the loop
jump is at or below the caller-supplied loop maximum. A jump,
a visible seam, or a loop jump above the maximum fails.

Failure contract: a malformed input (not a JSON object) raises
:class:`CapabilityError`. A well-formed input with missing
thresholds or scores returns ``verdict: "not_checked"``; a
well-formed, fully supplied input that violates a threshold
returns ``verdict: "fail"``. Neither raises.
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


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_seam_loop_scores(data: Any) -> dict[str, Any]:
    """Judge seam scores and a loop jump against caller thresholds."""
    if not isinstance(data, dict):
        raise CapabilityError(
            "qa.seam_loop_vocabulary: input must be a JSON object"
        )
    issues: list[dict[str, Any]] = []
    thresholds = data.get("thresholds")
    if not isinstance(thresholds, dict):
        issues.append(
            _issue(
                "thresholds_missing",
                "thresholds must be supplied by the caller: "
                "seam_invisible_max, seam_jump_min and loop_jump_max; "
                "this gate has no default thresholds",
            )
        )
        thresholds = {}
    invisible_max = thresholds.get("seam_invisible_max")
    jump_min = thresholds.get("seam_jump_min")
    loop_max = thresholds.get("loop_jump_max")
    thresholds_ok = True
    for name, value in (
        ("seam_invisible_max", invisible_max),
        ("seam_jump_min", jump_min),
        ("loop_jump_max", loop_max),
    ):
        if not _is_num(value):
            thresholds_ok = False
            issues.append(
                _issue(
                    "threshold_missing",
                    f"threshold {name!r} must be supplied by the caller "
                    "as a number; no default is used",
                    threshold=name,
                )
            )
    if (
        thresholds_ok
        and not (float(invisible_max) < float(jump_min))
    ):
        thresholds_ok = False
        issues.append(
            _issue(
                "threshold_order_invalid",
                "seam_invisible_max must be below seam_jump_min, so a "
                "score has exactly one classification band",
            )
        )
    scores = data.get("seam_scores")
    if not isinstance(scores, list) or not scores:
        issues.append(
            _issue(
                "seam_scores_missing",
                "seam_scores must be a non-empty list; missing scores "
                "are not_checked, never a pass",
            )
        )
        scores = []
    loop = data.get("loop")
    loop_jump = loop.get("jump") if isinstance(loop, dict) else None
    if not _is_num(loop_jump):
        issues.append(
            _issue(
                "loop_jump_missing",
                "loop.jump must be supplied as a number; a missing "
                "loop measurement is not_checked, never a pass",
            )
        )
    if not thresholds_ok or not scores or not _is_num(loop_jump):
        return {
            "verdict": "not_checked",
            "ok": False,
            "seams": [],
            "loop": {"jump": loop_jump},
            "thresholds": thresholds,
            "issues": issues,
        }
    seams: list[dict[str, Any]] = []
    for index, score in enumerate(scores):
        if not _is_num(score):
            issues.append(
                _issue(
                    "seam_score_not_numeric",
                    f"seam score {index} must be a number",
                    index=index,
                    score=score,
                )
            )
            continue
        value = float(score)
        if value <= float(invisible_max):
            classification = "invisible"
        elif value > float(jump_min):
            classification = "jump"
        else:
            classification = "visible"
        seams.append(
            {"index": index, "score": value, "class": classification}
        )
        if classification == "jump":
            issues.append(
                _issue(
                    "seam_jump",
                    f"seam {index} score {value} is above the "
                    "caller-supplied jump minimum; it is a visible jump",
                    index=index,
                    score=value,
                )
            )
        elif classification == "visible":
            issues.append(
                _issue(
                    "seam_visible",
                    f"seam {index} score {value} is visible: above the "
                    "invisible maximum and at or below the jump minimum",
                    index=index,
                    score=value,
                )
            )
    loop_ok = float(loop_jump) <= float(loop_max)
    if not loop_ok:
        issues.append(
            _issue(
                "loop_jump_too_large",
                f"loop jump {loop_jump} is above the caller-supplied "
                f"loop maximum {loop_max}",
                jump=loop_jump,
            )
        )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "seams": seams,
        "loop": {"jump": float(loop_jump), "within_max": loop_ok},
        "thresholds": thresholds,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_seam_loop_scores(params.get("scores"))
    report_path = out_dir / "seam_loop_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass"},
    )


def register_seam_loop_vocabulary_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.seam_loop_vocabulary",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"scores": {"type": "object"}},
                "required": ["scores"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Seam and loop scoring vocabulary (open-3d-skills "
                "scroll-film / motion-assets discipline, clean-room): "
                "seam scores are classified invisible/visible/jump and "
                "a loop jump is judged only against caller-supplied "
                "thresholds, which have no defaults; missing thresholds "
                "or scores are not_checked, never a pass. Judges scores "
                "only; measures nothing. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.seam_loop_vocabulary"]


register_seam_loop_vocabulary_capabilities_once()
