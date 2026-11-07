"""Long-running job guard (file-based, clean-room, minimal).

Runs a registered ``hevi.capabilities`` capability in a background thread,
records the lifecycle on disk and always leaves a completion notification.
No database and no queue service: the jobs directory *is* the state.
"""

from __future__ import annotations

from hevi.jobguard.runner import (
    TERMINAL_STATUSES,
    default_jobs_root,
    get_job_status,
    list_notifications,
    resolve_jobs_root,
    start_job,
    wait_for_job,
)

__all__ = [
    "TERMINAL_STATUSES",
    "default_jobs_root",
    "get_job_status",
    "list_notifications",
    "resolve_jobs_root",
    "start_job",
    "wait_for_job",
]
