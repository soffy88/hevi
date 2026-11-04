"""Task recovery execution contract (``qa.task_recovery_contract``).

Fake execution contract for resuming an interrupted media task.
The real recovery -- re-running only the unfinished segments of
a task through a provider -- lives behind a channel the caller
supplies; this module only proves the recovery step, against a
fake backend, so the contract can be tested without a key, a
model, or a GPU:

1. The checkpoint is checked by ``qa.task_recovery_gate``. A
   recovery without a checkpoint, or one that re-runs finished
   segments, throws ``CapabilityError`` here, at plan time.
2. The recovery plan that passes lists exactly the unfinished
   segments, in order, resuming from the recorded position.
   Finished segments are recorded as skipped, never scheduled.
3. The fake run walks the remaining segments and records each
   as completed in order. It produces no media and spends
   nothing; the record is the evidence that no finished segment
   was re-run.

No task is executed for real, no key is stored, nothing is
spent. Method ideas borrowed, text self-written, from
HBAI-Ltd/Toonflow-app (MIT, verified against the repository
LICENSE file; the MIT licence covers that repository only).
No Toonflow text, code or assets are copied here.
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
from hevi.capabilities.pure_helpers import (
    check_task_recovery,
)

_Registered = False


def plan_recovery(
    plan: Any,
    *,
    checkpoint: Any = None,
) -> dict[str, Any]:
    """Build a recovery plan from a checkpoint (fake).

    Raises ``CapabilityError`` when the checkpoint cannot support
    a recovery. On success returns the plan: the unfinished
    segments in order, the resume position, and the finished
    segments recorded as skipped.
    """
    report = check_task_recovery(plan, checkpoint=checkpoint)
    if not report["ok"]:
        problems = "; ".join(
            f"{p['code']}: {p['detail']}" for p in report["problems"]
        )
        raise CapabilityError(
            "qa.task_recovery_contract: recovery plan refused: "
            f"{problems}"
        )
    record = checkpoint if checkpoint is not None else plan.get("checkpoint")
    segments = list(plan["segments"])
    completed = list(report["completed_segments"])
    remaining = [s for s in segments if s not in completed]
    return {
        "ok": True,
        "task_id": report["task_id"],
        "resume_from": record.get("position"),
        "segments_to_run": remaining,
        "skipped_completed": completed,
        "checkpoint_state": record.get("state"),
    }


def execute_recovery_fake(
    plan: Any,
    *,
    checkpoint: Any = None,
) -> dict[str, Any]:
    """Walk the recovery plan against the fake backend.

    Records each remaining segment as completed, in order, and
    returns the run record. Finished segments appear only under
    ``skipped_completed``; a run that re-ran one would fail the
    gate before this step runs.
    """
    recovery = plan_recovery(plan, checkpoint=checkpoint)
    run: list[dict[str, Any]] = []
    for index, segment in enumerate(recovery["segments_to_run"]):
        run.append(
            {
                "segment": segment,
                "order": index + 1,
                "result": "completed",
                "backend": "fake",
            }
        )
    return {
        "ok": True,
        "task_id": recovery["task_id"],
        "resume_from": recovery["resume_from"],
        "ran": run,
        "ran_count": len(run),
        "skipped_completed": recovery["skipped_completed"],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    try:
        result = execute_recovery_fake(
            params.get("plan"),
            checkpoint=params.get("checkpoint"),
        )
    except CapabilityError as exc:
        result = {"ok": False, "error": str(exc), "ran": []}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "task_recovery_contract_run.json"
    record_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "record_json": str(record_path),
            "ok": result["ok"],
        },
    )


def register_task_recovery_contract_capabilities_once() -> list[str]:
    """Register ``qa.task_recovery_contract`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.task_recovery_contract",
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
                "Task recovery execution contract (fake backend): "
                "builds a recovery plan from a checkpoint and walks "
                "only the unfinished segments, recording finished "
                "segments as skipped. No real task runs, no key is "
                "stored."
            ),
            line="qa",
        )
    )
    return ["qa.task_recovery_contract"]
