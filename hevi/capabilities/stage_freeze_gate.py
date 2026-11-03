"""Stage freeze gate (``qa.stage_freeze_gate``).

Clean-room rewrite of the milestone-and-freeze method in
``hevi-vs-oyasumi-gamedev.md`` item 6 (from the oyasumi-gamedev.com
game-development series, restated in the report's own words): a
production moves through stages -- prototype, vertical slice,
alpha, beta, master -- and each stage ends in a milestone, a
written decision point to continue, change, or stop. At the
milestone the stage's work is frozen: the prototype answers
whether the thing should be made at all and may then be thrown
away; the vertical slice sets the quality bar and the working
time. Later work builds on frozen work only. Changing frozen
work is a new version, declared as a review, not a quiet edit.

This gate judges a stage plan -- records supplied by the caller.
It checks:

1. Stage names come from the closed, ordered vocabulary
   (prototype, vertical_slice, alpha, beta, master).
2. A stage may be used as the input of the next stage only when
   it is frozen; building on unfrozen work fails.
3. A frozen stage must list its frozen contents; a freeze with no
   contents fails.
4. Advancing past a stage requires its arrival conditions to be
   met; advancing without them fails.
5. Changing the contents of a frozen stage without a declared
   re-review fails -- the same explicit-declaration discipline as
   a reviewed floor elsewhere in hevi.

This module judges plans only. It never generates, never calls a
model, never touches a budget.
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

STAGES = ("prototype", "vertical_slice", "alpha", "beta", "master")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.stage_freeze_gate: {detail}"}
    issue.update(extra)
    return issue


def check_stage_freeze(plan: Any) -> dict[str, Any]:
    """Judge one stage plan. Returns ``ok`` / ``verdict`` / ``issues``.

    ``plan`` is an object with ``stages``: a list of objects with
    ``name`` (one of the five stages), ``frozen`` (bool),
    ``frozen_contents`` (a list, required when frozen),
    ``arrival_conditions_met`` (bool), and optional
    ``inputs_from`` (a list of stage names this stage builds on);
    and optional ``changes``: a list of objects with ``stage`` and
    ``re_review_declared`` (bool).
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("plan_not_object", "stage plan must be an object")],
        }
    stages = plan.get("stages")
    if not isinstance(stages, list) or not stages:
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("stages_missing", "stage plan must list at least one stage")],
        }
    records: dict[str, dict[str, Any]] = {}
    seen_order: list[str] = []
    for index, stage in enumerate(stages):
        where = f"stage {index}"
        if not isinstance(stage, dict):
            issues.append(_issue("stage_not_object", f"{where} must be an object"))
            continue
        name = stage.get("name")
        if name not in STAGES:
            issues.append(
                _issue(
                    "stage_unknown",
                    f"{where} must name a stage prototype/vertical_slice/"
                    f"alpha/beta/master, got {name!r}",
                )
            )
            continue
        if name in records:
            issues.append(_issue("stage_duplicate", f"stage {name!r} listed twice"))
            continue
        records[name] = stage
        seen_order.append(name)
        frozen = stage.get("frozen") is True
        contents = stage.get("frozen_contents")
        if frozen and (not isinstance(contents, list) or not contents):
            issues.append(
                _issue(
                    "frozen_without_contents",
                    f"stage {name!r} is frozen but lists no frozen contents",
                    stage=name,
                )
            )
        if stage.get("arrival_conditions_met") is not True:
            later = [s for s in seen_order if STAGES.index(s) > STAGES.index(name)]
            if later:
                issues.append(
                    _issue(
                        "stage_advance_without_conditions",
                        f"stage {name!r} was advanced past but its arrival "
                        "conditions are not met",
                        stage=name,
                    )
                )
        for source in stage.get("inputs_from") or []:
            source_record = records.get(source)
            if source_record is None:
                issues.append(
                    _issue(
                        "input_stage_unknown",
                        f"stage {name!r} builds on unknown stage {source!r}",
                        stage=name,
                    )
                )
            elif source_record.get("frozen") is not True:
                issues.append(
                    _issue(
                        "unfrozen_input",
                        f"stage {name!r} builds on stage {source!r}, which "
                        "is not frozen; only frozen work may feed the "
                        "next stage",
                        stage=name,
                    )
                )
    order_indexes = [STAGES.index(name) for name in seen_order]
    if order_indexes != sorted(order_indexes):
        issues.append(
            _issue(
                "stage_order_broken",
                "stages must be listed in production order: prototype, "
                "vertical_slice, alpha, beta, master",
            )
        )
    for change in plan.get("changes") or []:
        if not isinstance(change, dict):
            issues.append(_issue("change_not_object", "each change must be an object"))
            continue
        stage_name = change.get("stage")
        record = records.get(stage_name)
        if record is None:
            issues.append(
                _issue("change_stage_unknown", f"change names unknown stage {stage_name!r}")
            )
        elif record.get("frozen") is True and change.get("re_review_declared") is not True:
            issues.append(
                _issue(
                    "frozen_change_without_review",
                    f"stage {stage_name!r} is frozen; changing its "
                    "contents requires a declared re-review",
                    stage=stage_name,
                )
            )
    verdict = "fail" if issues else "pass"
    return {"ok": verdict == "pass", "verdict": verdict, "issues": issues}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_stage_freeze(params.get("plan"))
    report_path = out_dir / "stage_freeze_gate.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_stage_freeze_gate_capabilities_once() -> list[str]:
    """Register ``qa.stage_freeze_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.stage_freeze_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Stage freeze gate: prototype/vertical_slice/alpha/beta/"
                "master in order, only frozen work feeds the next stage, "
                "frozen stages list their contents, advancing requires "
                "met arrival conditions, and changing frozen contents "
                "requires a declared re-review. Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.stage_freeze_gate"]


register_stage_freeze_gate_capabilities_once()
