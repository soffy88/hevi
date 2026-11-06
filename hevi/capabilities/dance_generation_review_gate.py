"""Dance generation review gate (``qa.dance_generation_review_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): nothing is
called good because it feels good. Before generation, a
sixteen-point checklist is walked item by item — music,
reference roles, person, environment, props, genre,
chain, capacity, footwork, physical camera, camera sync,
edit reason, self-containment, language, sound, and no
mechanical fault. After generation, ten dimensions are
scored one to five — person and scene consistency,
rhythm sync, action completeness, dynamics, genre
style, camera quality, shot readability, transition
value, and overall commercial feel. When something is
wrong, the failure is first placed in one of seven
layers — material, timing, choreography, camera,
continuity, language, or generation randomness — and
each symptom is fixed where it lives, with the check
that found it and the repair written down. This gate
judges the review record only. It generates nothing,
renders nothing, and spends nothing: ``executed_here``
is always false.
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

# Sixteen pre-generation checks, walked item by item.
PREFLIGHT_KEYS: tuple[str, ...] = (
    "music",
    "reference",
    "person",
    "environment",
    "props",
    "genre",
    "chain",
    "capacity",
    "footwork",
    "camera_physical",
    "camera_sync",
    "edit_reason",
    "self_contained",
    "language",
    "sound",
    "mechanical",
)

# Ten post-generation dimensions, scored one to five.
POST_DIMS: tuple[str, ...] = (
    "person_consistency",
    "scene_consistency",
    "rhythm_sync",
    "action_completeness",
    "dynamics_credibility",
    "genre_style",
    "camera_quality",
    "shot_readability",
    "transition_value",
    "commercial_feel",
)

# Seven layers a failure is placed in before it is fixed.
DIAGNOSIS_LAYERS: frozenset[str] = frozenset(
    {
        "material",
        "timing",
        "choreography",
        "camera",
        "continuity",
        "language",
        "randomness",
    }
)
OVERALL_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "revise"})
VAGUE_PHRASES: tuple[str, ...] = ("feels good", "整体感觉不错", "looks fine")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_generation_review(review: Any) -> dict[str, Any]:
    """Validate a generation review record for one dance segment.

    Verdicts are ``pass`` / ``fail`` only. The review fails
    when any pre-generation check is missing or unchecked,
    when any post-generation score is missing or outside
    one to five, when the failure layer is unknown or its
    cause is unwritten, when any fix lacks its symptom,
    check or repair, or when the overall verdict is a vague
    feeling instead of a graded judgement.
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
        return fail("review_not_object", "generation review must be a JSON object")
    preflight = review.get("preflight")
    if not isinstance(preflight, dict):
        return fail(
            "preflight_missing",
            "review must carry its pre-generation checklist",
        )
    items = preflight.get("items")
    if not isinstance(items, dict):
        return fail(
            "preflight_items_missing",
            "pre-generation checklist must carry its items",
        )
    for key in PREFLIGHT_KEYS:
        if items.get(key) is not True:
            return fail(
                "preflight_incomplete",
                f"pre-generation check {key!r} is missing or unchecked",
            )
    scores = review.get("post_scores")
    if not isinstance(scores, dict):
        return fail(
            "post_scores_missing",
            "review must carry its post-generation scores",
        )
    worst = 5
    for dim in POST_DIMS:
        value = scores.get(dim)
        if value is None:
            return fail(
                "score_missing",
                f"post-generation dimension {dim!r} has no score",
            )
        if not isinstance(value, int) or isinstance(value, bool):
            return fail(
                "score_not_integer",
                f"post-generation dimension {dim!r} must be scored 1-5",
            )
        if value < 1 or value > 5:
            return fail(
                "score_out_of_range",
                f"post-generation dimension {dim!r} is scored {value}; the range is 1-5",
            )
        worst = min(worst, value)
    diagnosis = review.get("diagnosis")
    if not isinstance(diagnosis, dict):
        return fail(
            "diagnosis_missing",
            "review must place any failure in one diagnosis layer",
        )
    if diagnosis.get("layer") not in DIAGNOSIS_LAYERS:
        return fail(
            "diagnosis_layer_unknown",
            "diagnosis layer must be one of the seven layers",
        )
    if not isinstance(diagnosis.get("cause"), str) or not diagnosis["cause"].strip():
        return fail(
            "diagnosis_cause_missing",
            "diagnosis must state the cause in plain words",
        )
    fixes = review.get("fixes")
    if not isinstance(fixes, list) or not fixes:
        return fail(
            "fixes_missing",
            "review must carry at least one symptom-to-fix record",
        )
    for position, fix in enumerate(fixes):
        if not isinstance(fix, dict):
            return fail(
                "fix_not_object",
                f"fix {position} must be an object",
            )
        for field in ("symptom", "check", "fix"):
            if not isinstance(fix.get(field), str) or not fix[field].strip():
                return fail(
                    "fix_incomplete",
                    f"fix {position} must state its {field}",
                )
    overall = review.get("overall")
    if overall not in OVERALL_VERDICTS:
        return fail(
            "overall_unknown",
            "overall verdict must be pass, fail or revise",
        )
    if overall == "pass" and worst == 1:
        return fail(
            "vague_overall_acceptance",
            "a dimension scored 1 cannot pass overall; a feeling never replaces a graded judgement",
        )
    note = review.get("overall_note", "")
    if isinstance(note, str):
        lowered = note.lower()
        for phrase in VAGUE_PHRASES:
            if phrase in lowered:
                return fail(
                    "vague_overall_acceptance",
                    f"overall note leans on vague phrase {phrase!r} instead of the graded scores",
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
    report = check_dance_generation_review(params.get("review"))
    report_path = out_dir / "dance_generation_review_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_generation_review_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_generation_review_gate",
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
                "Dance generation review gate: sixteen-point "
                "pre-generation checklist, ten dimensions scored "
                "1-5, seven-layer failure diagnosis, and "
                "symptom-to-fix records; no vague acceptance."
            ),
        )
    )
    return ["qa.dance_generation_review_gate"]


__all__ = [
    "DIAGNOSIS_LAYERS",
    "OVERALL_VERDICTS",
    "POST_DIMS",
    "PREFLIGHT_KEYS",
    "VAGUE_PHRASES",
    "check_dance_generation_review",
    "register_dance_generation_review_gate_capabilities_once",
]
