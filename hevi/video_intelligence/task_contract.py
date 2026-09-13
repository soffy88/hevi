"""Typed task preflight without creating another queue/orchestration authority."""

from __future__ import annotations

from pathlib import Path

from .models import PreflightResult, VideoTask


def preflight_video(path: str | Path, *, output_dir: str | Path) -> PreflightResult:
    target = Path(path)
    destination = Path(output_dir)
    checks = {
        "video_exists": target.is_file() and target.stat().st_size > 0,
        "output_writable": (destination.exists() and destination.is_dir()) or destination.parent.exists(),
    }
    errors = [name for name, passed in checks.items() if not passed]
    return PreflightResult(status="READY" if not errors else "BLOCKED", checks=checks, errors=errors)


def validate_task_dependencies(task: VideoTask, completed: set[str]) -> PreflightResult:
    missing = [dependency for dependency in task.dependencies if dependency not in completed]
    return PreflightResult(
        status="READY" if not missing else "BLOCKED",
        checks={dependency: dependency in completed for dependency in task.dependencies},
        errors=[f"TASK_DEPENDENCY_FAILED:{dependency}" for dependency in missing],
    )
