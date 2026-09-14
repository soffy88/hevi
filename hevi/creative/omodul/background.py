"""Runtime-owned background run control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from hevi.obase.creative import FailureRecord, ProductionRun

_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


@dataclass(frozen=True)
class ProgressEvent:
    """Deterministic progress derived from persisted stage results."""

    run_id: str
    status: str
    stage: str | None
    completed_stages: int
    total_stages: int
    percent: float

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "stage": self.stage,
            "completed_stages": self.completed_stages,
            "total_stages": self.total_stages,
            "percent": self.percent,
        }


class BackgroundRunController:
    def progress(self, run: ProductionRun) -> ProgressEvent:
        total = len(run.stage_results)
        completed = sum(item.status in _TERMINAL for item in run.stage_results)
        current = next(
            (item.stage for item in reversed(run.stage_results) if item.status == "RUNNING"),
            None,
        )
        return ProgressEvent(
            run_id=str(run.object_id),
            status=run.status,
            stage=current,
            completed_stages=completed,
            total_stages=total,
            percent=round(completed / total * 100, 4) if total else 0.0,
        )

    def notification(self, event: ProgressEvent) -> dict[str, object]:
        return {
            "event_type": f"creative.run.{event.status.lower()}",
            "run_id": event.run_id,
            "stage": event.stage,
            "percent": event.percent,
        }

    def cancel(self, run: ProductionRun) -> ProductionRun:
        if run.status in _TERMINAL:
            return run
        return run.model_copy(
            update={
                "status": "CANCELLED",
                "updated_at": datetime.now(UTC),
                "revision": run.revision + 1,
            }
        )

    def retry(self, run: ProductionRun) -> ProductionRun:
        if run.status not in {"FAILED", "BLOCKED"}:
            raise ValueError("only failed or blocked runs can be retried")
        return run.model_copy(
            update={
                "status": "RUNNING",
                "failure": None,
                "updated_at": datetime.now(UTC),
                "revision": run.revision + 1,
            }
        )

    def fail(self, run: ProductionRun, failure: FailureRecord) -> ProductionRun:
        return run.model_copy(
            update={
                "status": "FAILED",
                "failure": failure,
                "updated_at": datetime.now(UTC),
                "revision": run.revision + 1,
            }
        )


__all__ = ["BackgroundRunController", "ProgressEvent"]
