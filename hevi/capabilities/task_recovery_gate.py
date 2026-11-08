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
from hevi.capabilities.pure_helpers import (
    CHECKPOINT_STATES,
    _task_recovery_issue as _issue,
    _segment_list,
    check_task_recovery,
)

_Registered = False









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
