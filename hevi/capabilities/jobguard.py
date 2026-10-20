"""Background job guard capabilities (clean-room, minimal).

Registers three ``hevi.capabilities`` entries backed by :mod:`hevi.jobguard`:

* ``job.run_background`` — start any registered capability in a background
  thread (params: ``capability`` + its ``params``, optional ``webhook_url``
  and ``jobs_root``).  Returns immediately with a ``job_id``; the job record
  lives at ``jobs/<job_id>/status.json``.
* ``job.status`` — read one job's status record.
* ``job.notifications`` — list completion notifications (every terminated
  job, success or failure, appends one to ``jobs/notifications.jsonl`` and
  writes ``jobs/<job_id>/notification.json``).  A given ``webhook_url``
  receives a best-effort POST of the notification; delivery failure is
  recorded in the notification and never changes the job's outcome.
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


def _render_run_background(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.jobguard import runner

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        job_id = runner.start_job(
            params["capability"],
            params.get("params") or {},
            jobs_root=params.get("jobs_root"),
            webhook_url=params.get("webhook_url"),
            duration=float(params.get("duration", duration)),
            aspect=str(params.get("aspect", aspect)),
            seed=int(params.get("seed", seed)),
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"job.run_background failed: {exc}") from exc

    root = runner.resolve_jobs_root(params.get("jobs_root"))
    record = {"job_id": job_id, "capability": params["capability"], "status": "running",
              "jobs_root": str(root)}
    snapshot = out_dir / "job.json"
    snapshot.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(snapshot),
        qa={**record, "snapshot": str(snapshot)},
    )


def _render_job_status(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.jobguard import runner

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        status = runner.get_job_status(params["job_id"], jobs_root=params.get("jobs_root"))
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"job.status failed: {exc}") from exc

    snapshot = out_dir / "job_status.json"
    snapshot.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(snapshot),
        qa={
            "job_id": status["job_id"],
            "status": status["status"],
            "capability": status.get("capability"),
            "error": status.get("error"),
            "job": status,
            "snapshot": str(snapshot),
        },
    )


def _render_job_notifications(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.jobguard import runner

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        notes = runner.list_notifications(
            jobs_root=params.get("jobs_root"), limit=int(params.get("limit", 50))
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"job.notifications failed: {exc}") from exc

    snapshot = out_dir / "notifications.json"
    snapshot.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(snapshot),
        qa={"notifications": notes, "count": len(notes), "snapshot": str(snapshot)},
    )


def register_jobguard_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="job.run_background",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "capability": {"type": "string", "minLength": 1},
                    "params": {"type": "object"},
                    "webhook_url": {"type": "string", "minLength": 1},
                    "jobs_root": {"type": "string", "minLength": 1},
                    "duration": {"type": "number"},
                    "aspect": {"type": "string"},
                    "seed": {"type": "integer"},
                },
                "required": ["capability"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_run_background,
            description=(
                "Run a registered capability in a background thread and guard "
                "it to completion: status lands in jobs/<job_id>/status.json, "
                "a completion notification is always written, and an optional "
                "webhook_url gets a best-effort POST."
            ),
            line="jobguard",
        )
    )
    registered.append("job.run_background")

    register(
        Capability(
            name="job.status",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "minLength": 1},
                    "jobs_root": {"type": "string", "minLength": 1},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_job_status,
            description="Read one background job's status record (running/succeeded/failed, times, artifacts, error).",
            line="jobguard",
        )
    )
    registered.append("job.status")

    register(
        Capability(
            name="job.notifications",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "jobs_root": {"type": "string", "minLength": 1},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_job_notifications,
            description="List recent background-job completion notifications from jobs/notifications.jsonl.",
            line="jobguard",
        )
    )
    registered.append("job.notifications")

    return registered
