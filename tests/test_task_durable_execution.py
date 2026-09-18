"""W11 gates: task_service persists, restarts, and never double-submits."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from hevi.tasks.durable_execution import (
    DurableExecutionError,
    load_record,
    submission_count,
)
from hevi.tasks.task_service import TaskService


class DictRepository:
    """JSON-roundtripping fake over the real repository interface.

    Every write serializes through JSON and every read deserializes, so
    persistence/serializability claims hold across service instances.
    """

    def __init__(self) -> None:
        self.pool = object()
        self._rows: dict[str, dict[str, Any]] = {}

    def seed(self, task: dict[str, Any]) -> uuid.UUID:
        task_id = uuid.uuid4()
        self._rows[str(task_id)] = json.loads(json.dumps({**task, "id": str(task_id)}))
        return task_id

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        row = self._rows.get(str(task_id))
        return json.loads(json.dumps(row)) if row is not None else None

    async def update_task(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        row = self._rows.get(str(task_id))
        if row is None:
            return False
        merged = json.loads(json.dumps({**row, **data}))
        self._rows[str(task_id)] = merged
        return True


def _intent(**kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "provider": "maas_lock",
        "endpoint": "https://provider.example/v1/jobs",
        "model": "happyhorse-1.1",
        "request": {"prompt": "雨夜街景", "duration_s": 5},
        "production_revision": "rev-9",
        "target_artifact_id": "clip-1",
        "idempotency_key": "idem-1",
    }
    args.update(kw)
    return args


async def _service_with_task() -> tuple[TaskService, DictRepository, uuid.UUID]:
    repo = DictRepository()
    service = TaskService(repo)  # type: ignore[arg-type]
    task_id = repo.seed({"status": "running", "config_json": {}})
    return service, repo, task_id


@pytest.mark.asyncio
async def test_task_service_durable_wiring() -> None:
    """TASK_SERVICE_DURABLE_WIRING: submit persists fingerprint + job lifecycle."""

    service, repo, task_id = await _service_with_task()
    opened = await service.begin_durable_execution(task_id, **_intent())
    assert opened["action"] == "submit"
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    task = await repo.get_task(task_id)
    assert task is not None
    record = load_record(task["config_json"])
    assert record is not None and record.provider_job_id == "job-1"
    assert submission_count(task["config_json"], record.request_fingerprint) == 1


@pytest.mark.asyncio
async def test_task_service_restart_recovery() -> None:
    """TASK_SERVICE_RESTART_RECOVERY: new instance resumes from the database."""

    service, repo, task_id = await _service_with_task()
    await service.begin_durable_execution(task_id, **_intent())
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    restarted = TaskService(repo)  # type: ignore[arg-type]
    decision = await restarted.recover_durable_execution(task_id)
    assert decision["action"] == "resume_poll"
    reopened = await restarted.begin_durable_execution(task_id, **_intent())
    assert reopened["action"] == "resume_poll"  # duplicate delivery resumes
    task = await repo.get_task(task_id)
    assert task is not None
    record = load_record(task["config_json"])
    assert record is not None
    assert submission_count(task["config_json"], record.request_fingerprint) == 1


@pytest.mark.asyncio
async def test_task_service_download_only_resume() -> None:
    """TASK_SERVICE_DOWNLOAD_ONLY_RESUME: remote success + crash => download only."""

    service, repo, task_id = await _service_with_task()
    await service.begin_durable_execution(task_id, **_intent())
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    await service.record_durable_event(
        task_id, {"kind": "remote_success", "remote_artifact_url": "https://cdn.example/c.mp4"}
    )
    await service.record_durable_event(
        task_id, {"kind": "download_progress", "received_bytes": 1024, "etag": "e1"}
    )
    restarted = TaskService(repo)  # type: ignore[arg-type]
    decision = await restarted.recover_durable_execution(task_id)
    assert decision["action"] == "resume_download"
    await restarted.record_durable_event(
        task_id,
        {
            "kind": "download_complete",
            "local_artifact_path": "/v/c.mp4",
            "checksum": "ab",
            "actual_cost": 0.45,
        },
    )
    task = await repo.get_task(task_id)
    assert task is not None
    record = load_record(task["config_json"])
    assert record is not None and record.done is True
    assert record.billing_state.value == "billed"
    assert record.provider_job_id == "job-1"  # same job, never re-submitted
    with pytest.raises(DurableExecutionError, match="DURABLE_EXECUTION_ALREADY_COMPLETE"):
        await restarted.record_durable_event(
            task_id,
            {
                "kind": "download_complete",
                "local_artifact_path": "/v/c.mp4",
                "checksum": "ab",
                "actual_cost": 0.45,
            },
        )
    task = await repo.get_task(task_id)
    assert task is not None
    assert load_record(task["config_json"]) is not None


@pytest.mark.asyncio
async def test_task_service_duplicate_submit_zero() -> None:
    """TASK_SERVICE_DUPLICATE_SUBMIT=0 / DUPLICATE_BILLING=0 under redelivery."""

    service, repo, task_id = await _service_with_task()
    first = await service.begin_durable_execution(task_id, **_intent())
    assert first["action"] == "submit"
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    second = await service.begin_durable_execution(task_id, **_intent())
    assert second["action"] == "resume_poll"
    task = await repo.get_task(task_id)
    assert task is not None
    record = load_record(task["config_json"])
    assert record is not None
    assert submission_count(task["config_json"], record.request_fingerprint) == 1
    with pytest.raises(DurableExecutionError, match="DURABLE_EXECUTION_DUPLICATE_SUBMIT"):
        await service.record_durable_event(
            task_id, {"kind": "submitted", "provider_job_id": "job-2"}
        )


@pytest.mark.asyncio
async def test_task_service_expired_remote_fails_explicitly() -> None:
    service, _repo, task_id = await _service_with_task()
    await service.begin_durable_execution(task_id, **_intent())
    await service.record_durable_event(task_id, {"kind": "submitted", "provider_job_id": "job-1"})
    await service.record_durable_event(task_id, {"kind": "remote_expired", "error": "job gone"})
    decision = await service.recover_durable_execution(task_id)
    assert decision["action"] == "explicit_fail"
