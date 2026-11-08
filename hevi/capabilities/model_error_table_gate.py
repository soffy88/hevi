"""Model error-table gate (``qa.model_error_table_gate``).

Clean-room restatement of the Eian short-film workflow
(see ``EIAN_WORKFLOW_ATTRIBUTION.md``): most bad shots
are prompt faults, not model faults, and the same faults
recur. This gate checks a prompt against the recurring
fault table, in the reviewer's own words — actions that
happen at the same moment must be written in turn, a
"do not" must be rewritten as a positive instruction,
counts must be written as numbers and match the frames,
a prop must not be used before it appears in the first
frame, and one shot must carry at most two main actions.
This gate judges the prompt record only. It generates
no video and spends nothing: ``executed_here`` is always
false. The fault frequencies in the source article are
the author's own case notes, not verified measurements,
and this gate does not repeat them as facts.
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

# Negative phrasings a model tends to ignore. A prompt line
# carrying one needs a declared positive rewrite. A bare
# "not" inside ordinary wording (for example a camera note
# that nothing pushes, pulls or shakes) is not a prohibition
# and is not flagged here.
NEGATION_MARKERS: tuple[str, ...] = (
    "不要",
    "do not",
    "don't",
    "never",
    "must not",
    "cannot",
)
MAX_MAIN_ACTIONS_PER_SHOT = 2


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _has_negation(line: str) -> bool:
    lowered = line.lower()
    return any(marker in line or marker in lowered for marker in NEGATION_MARKERS)


def check_model_error_table(prompt: Any) -> dict[str, Any]:
    """Validate a prompt against the recurring fault table.

    Verdicts are ``pass`` / ``fail`` only. A prompt fails
    when a negative line has no positive rewrite, when two
    actors do the same thing at the same second, when a
    declared count does not match the frames, when an action
    uses a prop missing from the first frame, or when one
    shot carries more than two main actions.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(prompt, dict):
        return fail("prompt_not_object", "prompt must be a JSON object")
    lines = prompt.get("lines")
    if not isinstance(lines, list):
        return fail("lines_missing", "prompt must carry its text lines")
    rewrites = prompt.get("positive_rewrites")
    if not isinstance(rewrites, list):
        rewrites = []
    rewritten = {entry.get("line") for entry in rewrites if isinstance(entry, dict)}
    for line in lines:
        if not isinstance(line, str):
            return fail("line_not_text", "prompt lines must be text")
        if _has_negation(line) and line not in rewritten:
            return fail(
                "negation_without_positive_rewrite",
                f"negative line {line!r} must be rewritten as a positive "
                "instruction; 'do not' phrasing is routinely ignored",
            )
    actions = prompt.get("actions")
    if isinstance(actions, list):
        if len(actions) > MAX_MAIN_ACTIONS_PER_SHOT:
            return fail(
                "too_many_main_actions",
                f"one shot carries {len(actions)} main actions; at most "
                f"{MAX_MAIN_ACTIONS_PER_SHOT}",
            )
        seen: dict[tuple[Any, str], str] = {}
        first_frame_items = prompt.get("first_frame_items")
        if not isinstance(first_frame_items, list):
            first_frame_items = []
        for position, action in enumerate(actions):
            if not isinstance(action, dict):
                return fail(
                    "action_not_object",
                    f"action {position} must be an object",
                )
            actor = action.get("actor")
            verb = action.get("action")
            delay = action.get("delay_s")
            if not isinstance(actor, str) or not actor.strip():
                return fail(
                    "action_actor_missing",
                    f"action {position} must name its actor",
                )
            if not isinstance(verb, str) or not verb.strip():
                return fail(
                    "action_verb_missing",
                    f"action {position} must name its action",
                )
            if not isinstance(delay, (int, float)):
                return fail(
                    "action_delay_missing",
                    f"action {position} must carry its delay in seconds",
                )
            key = (delay, verb)
            if key in seen:
                return fail(
                    "simultaneous_action",
                    f"{actor} and {seen[key]} do {verb!r} at the same "
                    "second; write who acts first and who follows",
                )
            seen[key] = actor
            prop = action.get("prop")
            if isinstance(prop, str) and prop and prop not in first_frame_items:
                return fail(
                    "prop_not_in_first_frame",
                    f"action {position} uses prop {prop!r}, which is absent from the first frame",
                )
    counts_declared = prompt.get("counts_declared")
    counts_in_frame = prompt.get("counts_in_frame")
    if isinstance(counts_declared, dict) and isinstance(counts_in_frame, dict):
        for item, count in counts_declared.items():
            if counts_in_frame.get(item) != count:
                return fail(
                    "count_mismatch",
                    f"declared count of {item!r} is {count}, but the "
                    f"frames show {counts_in_frame.get(item)}",
                )
    elif isinstance(counts_declared, dict) and counts_declared:
        return fail(
            "counts_not_verified",
            "declared counts need matching frame counts to check against",
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
    report = check_model_error_table(params.get("prompt"))
    report_path = out_dir / "model_error_table_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_model_error_table_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.model_error_table_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "object"},
                },
                "required": ["prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Model error-table gate: actions in turn, negatives "
                "rewritten positively, counts written as numbers and "
                "matching the frames, props present in the first frame, "
                "at most two main actions per shot."
            ),
        )
    )
    return ["qa.model_error_table_gate"]


__all__ = [
    "MAX_MAIN_ACTIONS_PER_SHOT",
    "NEGATION_MARKERS",
    "check_model_error_table",
    "register_model_error_table_gate_capabilities_once",
]
