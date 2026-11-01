"""Task recovery state gate (``qa.task_recovery_gate``).

Clean-room restatement of the "recovery needs a checkpoint"
discipline behind Toonflow's media-task recovery (see
``TOONFLOW_RECHECK_ATTRIBUTION.md``): a task that was
interrupted may resume, but only from a recorded checkpoint.
A plan that calls itself a recovery without one is a restart
wearing a recovery's name, and a recovery that re-runs finished
segments wastes the work already paid for. This gate judges
recovery plans:

1. A recovery claim must carry a checkpoint record: task id,
   completed segments, resume position, and the time it was
   recorded. No checkpoint, no recovery.
2. The checkpoint must belong to the same task. A checkpoint
   from another task fails and names both ids.
3. The checkpoint must record an interrupted state
   (``interrupted``, ``paused`` or ``failed``). A checkpoint
   for a task that already finished cannot be resumed.
4. Segments the checkpoint lists as completed must not be
   scheduled again. Re-running a finished segment fails and
   names it.
5. The resume position must name a segment that exists, is not
   completed, and is in the plan's remaining work. Restarting
   from the beginning and calling it a recovery fails.

This gate judges plans only. It runs no task, spends nothing,
and never rewrites a plan to make it pass. The fake execution
contract that carries a checkpoint forward is
``qa.task_recovery_contract``.
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

CHECKPOINT_STATES = ("interrupted", "paused", "failed")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.task_recovery_gate: {detail}"}
    issue.update(extra)
    return issue


def _segment_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise CapabilityError(
            f"qa.task_recovery_gate: {field} must be a list of segment ids"
        )
    for item in value:
        if not isinstance(item, str) or not item:
            raise CapabilityError(
                f"qa.task_recovery_gate: every {field} entry must be a "
                "non-empty segment id string"
            )
    if len(set(value)) != len(value):
        raise CapabilityError(
            f"qa.task_recovery_gate: {field} lists a segment twice"
        )
    return list(value)


def check_task_recovery(
    plan: Any,
    *,
    checkpoint: Any = None,
) -> dict[str, Any]:
    """Check a recovery plan against its checkpoint record.

    ``plan`` carries ``task_id``, ``segments`` (the full segment
    list), ``segments_to_run`` and ``rerun_from_start``. The
    checkpoint may be passed separately or carried inside the
    plan under ``checkpoint``. Returns a report with ``ok`` and
    the problems.
    """
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.task_recovery_gate: plan must be an object"
        )
    record = checkpoint if checkpoint is not None else plan.get("checkpoint")
    problems: list[dict[str, Any]] = []
    task_id = plan.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise CapabilityError(
            "qa.task_recovery_gate: plan needs a non-empty task_id string"
        )
    segments = _segment_list(plan.get("segments", []), "segments")
    to_run = _segment_list(plan.get("segments_to_run", []), "segments_to_run")

    if record is None:
        problems.append(
            _issue(
                "missing_checkpoint",
                f"task {task_id!r} claims recovery but carries no "
                "checkpoint record; without one it is a restart, "
                "not a recovery",
                task_id=task_id,
            )
        )
        return {
            "ok": False,
            "task_id": task_id,
            "problems": problems,
        }
    if not isinstance(record, dict):
        raise CapabilityError(
            "qa.task_recovery_gate: checkpoint must be an object"
        )
    if record.get("task_id") != task_id:
        problems.append(
            _issue(
                "checkpoint_task_mismatch",
                "checkpoint belongs to task "
                f"{record.get('task_id')!r}, not {task_id!r}",
                task_id=task_id,
                checkpoint_task_id=record.get("task_id"),
            )
        )
    state = record.get("state")
    if state not in CHECKPOINT_STATES:
        problems.append(
            _issue(
                "checkpoint_not_resumable",
                f"checkpoint state {state!r} is not resumable; only "
                f"{list(CHECKPOINT_STATES)} checkpoints resume",
                state=state,
            )
        )
    completed = _segment_list(
        record.get("completed_segments", []), "completed_segments"
    )
    unknown_completed = [s for s in completed if s not in segments]
    if unknown_completed:
        problems.append(
            _issue(
                "checkpoint_unknown_segment",
                "checkpoint lists completed segments that are not in "
                f"the plan: {unknown_completed}",
                segments=unknown_completed,
            )
        )
    rerun = [s for s in to_run if s in completed]
    if rerun:
        problems.append(
            _issue(
                "reruns_completed_segment",
                "recovery re-runs finished segments instead of "
                f"skipping them: {rerun}",
                segments=rerun,
            )
        )
    unknown_run = [s for s in to_run if s not in segments]
    if unknown_run:
        problems.append(
            _issue(
                "unknown_segment_to_run",
                f"plan schedules segments that do not exist: {unknown_run}",
                segments=unknown_run,
            )
        )
    if plan.get("rerun_from_start") is True:
        problems.append(
            _issue(
                "restart_claimed_as_recovery",
                "plan restarts from the beginning and calls it "
                "recovery; a recovery resumes from its checkpoint",
            )
        )
    position = record.get("position")
    if position is not None:
        if position not in segments:
            problems.append(
                _issue(
                    "checkpoint_position_unknown",
                    f"checkpoint position {position!r} is not a segment "
                    "of this task",
                    position=position,
                )
            )
        elif position in completed:
            problems.append(
                _issue(
                    "checkpoint_position_completed",
                    f"checkpoint position {position!r} is already "
                    "completed; resuming there re-runs finished work",
                    position=position,
                )
            )
        elif position not in to_run:
            problems.append(
                _issue(
                    "checkpoint_position_not_scheduled",
                    f"checkpoint position {position!r} is not in the "
                    "plan's remaining work",
                    position=position,
                )
            )
    if record.get("recorded_at") is None:
        problems.append(
            _issue(
                "checkpoint_undated",
                "checkpoint carries no recorded_at time; an undated "
                "checkpoint cannot be ordered against later work",
            )
        )
    return {
        "ok": not problems,
        "task_id": task_id,
        "completed_segments": completed,
        "problems": problems,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_task_recovery(
        params.get("plan"),
        checkpoint=params.get("checkpoint"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "task_recovery_gate_report.json"
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


def register_task_recovery_gate_capabilities_once() -> list[str]:
    """Register ``qa.task_recovery_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.task_recovery_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "checkpoint": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Task recovery state gate: a recovery claim must carry "
                "a checkpoint for the same task in a resumable state, "
                "must not re-run finished segments, and must resume "
                "from its recorded position. Plans without a checkpoint "
                "are restarts, not recoveries. Plans are checked, never "
                "rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.task_recovery_gate"]
