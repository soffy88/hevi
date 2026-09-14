"""Runtime-owned background run control."""

from __future__ import annotations

from datetime import UTC, datetime

from hevi.obase.creative import FailureRecord, ProductionRun


class BackgroundRunController:
    def cancel(self, run: ProductionRun) -> ProductionRun:
        if run.status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
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


__all__ = ["BackgroundRunController"]
