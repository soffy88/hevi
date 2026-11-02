"""Status-card monotonicity gate (``qa.status_card_monotonic_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / A3: a character's or prop's status card only moves
forward. The caller declares the ordered state ladder for each
subject (``state_order``); every declaration in play order must
sit at the same rung or higher. A step back down the ladder
fails, unless the declaration carries a rest-or-treatment
justification -- a character may recover on screen, but the
recovery must be declared, not smuggled in as a silent reset.
Excused regressions are recorded in the evidence, never hidden.

This module judges plans only. It reads no media bytes and
calls no generator.
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

_EXCUSING_JUSTIFICATIONS = {"rest", "treatment"}


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_status_cards(plan: Any) -> dict[str, Any]:
    """Judge one status-card plan. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    excused: list[dict[str, Any]] = []
    subjects_out: list[dict[str, Any]] = []

    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "subjects": [],
            "excused_regressions": [],
            "issues": [
                _issue(
                    "plan_not_object",
                    "qa.status_card_monotonic_gate: status-card plan must "
                    "be an object",
                )
            ],
        }

    subjects = plan.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        issues.append(
            _issue(
                "subjects_missing",
                "qa.status_card_monotonic_gate: the plan needs a "
                "non-empty 'subjects' list",
            )
        )
        subjects = []

    for index, subject in enumerate(subjects):
        label = f"subject {index + 1}"
        if not isinstance(subject, dict):
            issues.append(
                _issue(
                    "subject_not_object",
                    f"qa.status_card_monotonic_gate: {label} must be an "
                    "object",
                )
            )
            continue
        subject_id = subject.get("subject_id")
        if _is_nonempty_str(subject_id):
            label = f"subject {subject_id}"
        entry: dict[str, Any] = {"label": label}
        state_order = subject.get("state_order")
        if (
            not isinstance(state_order, list)
            or not state_order
            or not all(_is_nonempty_str(s) for s in state_order)
            or len(set(state_order)) != len(state_order)
        ):
            issues.append(
                _issue(
                    "state_order_missing",
                    f"qa.status_card_monotonic_gate: {label} must declare "
                    "'state_order' as a non-empty list of distinct state "
                    "codes; without a ladder, forward cannot be judged",
                )
            )
            subjects_out.append(entry)
            continue
        rung = {code: i for i, code in enumerate(state_order)}
        entry["state_order"] = list(state_order)
        declarations = subject.get("declarations")
        if not isinstance(declarations, list) or not declarations:
            issues.append(
                _issue(
                    "declarations_missing",
                    f"qa.status_card_monotonic_gate: {label} needs a "
                    "non-empty 'declarations' list in play order",
                )
            )
            subjects_out.append(entry)
            continue
        last_rung = -1
        last_episode: int | None = None
        for pos, decl in enumerate(declarations):
            dlabel = f"{label} declaration {pos + 1}"
            if not isinstance(decl, dict):
                issues.append(
                    _issue(
                        "declaration_not_object",
                        f"qa.status_card_monotonic_gate: {dlabel} must be "
                        "an object",
                    )
                )
                continue
            episode_no = decl.get("episode_no")
            if (
                not isinstance(episode_no, int)
                or isinstance(episode_no, bool)
                or episode_no < 1
            ):
                issues.append(
                    _issue(
                        "episode_no_missing",
                        f"qa.status_card_monotonic_gate: {dlabel} must "
                        "declare a positive 'episode_no'",
                    )
                )
            elif last_episode is not None and episode_no < last_episode:
                issues.append(
                    _issue(
                        "declarations_out_of_order",
                        f"qa.status_card_monotonic_gate: {dlabel} episode "
                        f"{episode_no} comes after episode {last_episode}; "
                        "declarations must be in play order",
                    )
                )
            else:
                last_episode = episode_no
            state = decl.get("state")
            if state not in rung:
                issues.append(
                    _issue(
                        "unknown_state",
                        f"qa.status_card_monotonic_gate: {dlabel} state "
                        f"{state!r} is not on the declared ladder "
                        f"{list(state_order)}",
                    )
                )
                continue
            here = rung[state]
            if here < last_rung:
                justification = decl.get("justification")
                note = decl.get("justification_note")
                if justification in _EXCUSING_JUSTIFICATIONS and _is_nonempty_str(note):
                    excused.append(
                        {
                            "subject": subject_id,
                            "episode_no": episode_no,
                            "state": state,
                            "justification": justification,
                            "note": note,
                        }
                    )
                else:
                    issues.append(
                        _issue(
                            "state_regression",
                            f"qa.status_card_monotonic_gate: {dlabel} "
                            f"steps back to {state!r} from rung "
                            f"{last_rung}; a status card only moves "
                            "forward unless a rest/treatment "
                            "justification with a note is declared",
                        )
                    )
            last_rung = max(last_rung, here)
        subjects_out.append(entry)

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "subjects": subjects_out,
        "excused_regressions": excused,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_status_cards(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "status_card_monotonic_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_status_card_monotonic_gate_capabilities_once() -> list[str]:
    """Register ``qa.status_card_monotonic_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.status_card_monotonic_gate",
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
                "Status-card monotonicity gate: each subject's state "
                "declarations must climb (never descend) its declared "
                "state ladder in play order; a step back fails unless a "
                "rest/treatment justification with a note is declared. "
                "Plans are judged, never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.status_card_monotonic_gate"]


register_status_card_monotonic_gate_capabilities_once()
