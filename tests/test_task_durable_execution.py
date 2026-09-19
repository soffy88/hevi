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
        self._rows[str(task_id)] = json.loads(json.dumps({**task, "id": str(task_id)}, default=str))
        return task_id

    async def get_task(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        row = self._rows.get(str(task_id))
        return json.loads(json.dumps(row)) if row is not None else None

    async def update_task(self, task_id: uuid.UUID, data: dict[str, Any]) -> bool:
        row = self._rows.get(str(task_id))
        if row is None:
            return False
        merged = json.loads(json.dumps({**row, **data}, default=str))
        self._rows[str(task_id)] = merged
        return True

    async def list_tasks(
        self, limit: int = 100, user_id: str | None = None, statuses: list[str] | None = None
    ) -> list[dict[str, Any]]:
        rows = [json.loads(json.dumps(r, default=str)) for r in self._rows.values()]
        if statuses:
            rows = [r for r in rows if r.get("status") in statuses]
        return rows[:limit]


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


@pytest.mark.asyncio
async def test_track_adapter_execution_persists_and_reconciles() -> None:
    """W17-A: task runtime observes execution; startup reconciliation routes."""

    from hevi.tasks.task_service import TaskService as _Svc

    repo = DictRepository()
    service = _Svc(repo)  # type: ignore[arg-type]
    task_id = repo.seed(
        {"status": "running", "topic": "t", "video_provider": "wan_cloud", "config_json": {}}
    )
    task = await repo.get_task(task_id)
    assert task is not None

    begun = await service.track_adapter_execution(task, phase="begin")
    assert begun["remote_state"] == "submitted"
    # observer re-entry must not record a second submit
    task = await repo.get_task(task_id)
    assert task is not None
    again = await service.track_adapter_execution(task, phase="begin")
    assert again["provider_job_id"] == str(task_id)

    task = await repo.get_task(task_id)
    assert task is not None
    done = await service.track_adapter_execution(
        task, phase="complete", artifact_path="/tmp/out.mp4"
    )
    assert done["remote_state"] == "remote_succeeded"
    assert done["acquisition_state"] == "download_complete"
    assert done["billing_state"] == "billed"

    report = await service.reconcile_on_startup()
    assert report["total"] >= 1
    entry = next(t for t in report["tasks"] if t["task_id"] == str(task_id))
    assert entry["action"] == "done"
    assert entry["provider_job_id"] == str(task_id)


@pytest.mark.asyncio
async def test_reconcile_routes_orphan_states() -> None:
    """STARTUP_RECONCILIATION: submitted -> resume_poll; success/dl-pending -> download."""

    from hevi.tasks.durable_execution import apply_execution_event, begin_execution

    repo = DictRepository()
    service = TaskService(repo)  # type: ignore[arg-type]
    poll_id = repo.seed({"status": "running", "config_json": {}})
    dl_id = repo.seed({"status": "running", "config_json": {}})

    intent = dict(
        provider="p",
        endpoint="e",
        model="m",
        request={"x": 1},
        production_revision="r1",
        target_artifact_id="t",
        idempotency_key="k",
    )
    poll_task = await repo.get_task(poll_id)
    assert poll_task is not None
    config, _rec, _action = begin_execution(dict(poll_task["config_json"]), **intent)
    config, _rec = apply_execution_event(
        config, {"kind": "submitted", "provider_job_id": "job-poll"}
    )
    await repo.update_task(poll_id, {"config_json": config})

    dl_task = await repo.get_task(dl_id)
    assert dl_task is not None
    config2, _rec2, _action2 = begin_execution(
        dict(dl_task["config_json"]), **{**intent, "target_artifact_id": "t2"}
    )
    config2, _rec2 = apply_execution_event(
        config2, {"kind": "submitted", "provider_job_id": "job-dl"}
    )
    config2, _rec2 = apply_execution_event(
        config2, {"kind": "remote_success", "remote_artifact_url": "https://cdn/x"}
    )
    await repo.update_task(dl_id, {"config_json": config2})

    report = await service.reconcile_on_startup()
    by_task = {t["task_id"]: t for t in report["tasks"]}
    assert by_task[str(poll_id)]["action"] == "resume_poll"
    assert by_task[str(dl_id)]["action"] == "resume_download"
    assert by_task[str(dl_id)]["provider_job_id"] == "job-dl"


@pytest.mark.asyncio
async def test_declarative_endpoint_runs_through_task_runtime(tmp_path, monkeypatch) -> None:
    """W17-B: registry -> task runtime -> executor -> ledger -> manifest/presentation."""

    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from hevi.creative.layer4.authority_stores import CallLedgerStore, EndpointRegistry
    from hevi.creative.layer4.endpoint_lifecycle import (
        AuthMode,
        CapabilityDeclaration,
        DeclarativeEndpointDefinition,
        SyncMode,
        enable,
        mark_validated,
        record_trial,
    )

    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    monkeypatch.setenv("HEVI_ENDPOINTS_DB", str(tmp_path / "endpoints.db"))
    monkeypatch.chdir(tmp_path)

    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg required for real-media presentation probe")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x128:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(clip),
            "-y",
        ],
        check=True,
    )
    file_bytes = clip.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        submits = 0

        def log_message(self, *a):
            pass

        def _json(self, payload):
            import json as _json

            body = _json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            type(self).submits += 1
            self._json({"video_url": f"http://127.0.0.1:{self.server.server_port}/f.mp4"})

        def do_GET(self):
            if self.path == "/f.mp4":
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(len(file_bytes)))
                self.end_headers()
                self.wfile.write(file_bytes)
                return
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        definition = DeclarativeEndpointDefinition(
            name="task-ep",
            provider_family="fake",
            base_url=f"{base}/v1/generate",
            auth_mode=AuthMode.NONE,
            request_schema={"properties": {"prompt": {}, "duration_s": {}}},
            request_template='{"prompt": "{{prompt}}"}',
            sync_mode=SyncMode.SYNC,
            artifact_url_path="video_url",
            capability=CapabilityDeclaration(media_type="video", durations_s=(5,), async_job=False),
        )
        enabled = enable(record_trial(mark_validated(definition), outcome="success"))
        EndpointRegistry().save(enabled.model_dump(mode="json"))

        repo = DictRepository()
        service = TaskService(repo)  # type: ignore[arg-type]
        task_id = repo.seed(
            {
                "status": "running",
                "topic": "t",
                "video_provider": "declarative_endpoint",
                "config_json": {
                    "production_source": "declarative_endpoint",
                    "endpoint_name": "task-ep",
                    "endpoint_params": {"prompt": "x", "duration_s": 5},
                    "endpoint_secrets": {},
                    "revision_id": "rev-1",
                },
            }
        )
        task = await repo.get_task(task_id)
        assert task is not None
        result = await service._run_declarative_endpoint(task)
        assert result["status"] == "completed"
        stored = await repo.get_task(task_id)
        assert stored is not None
        config = stored["config_json"]
        assert config["artifact_manifest"]["artifacts"][0]["artifact_id"] == str(task_id)
        assert config["presentation_snapshot"]["video"]["artifact_id"] == str(task_id)
        assert Handler.submits == 1
        rows, total = CallLedgerStore().list_records()
        assert total == 1 and rows[0]["status"] == "succeeded"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_failure_classification_single_source() -> None:
    """E09: provider failures normalize to stable codes, never UnknownError."""

    from hevi.creative.layer4.plan_projection import classify_failure_code

    assert classify_failure_code("DURABLE_SUBMIT_REJECTED:HTTP 429: busy") == "RATE_LIMITED"
    assert classify_failure_code("DURABLE_SUBMIT_REJECTED:HTTP 500: boom") == "SERVER_ERROR"
    assert classify_failure_code("DURABLE_POLL_TIMEOUT:600s") == "TIMEOUT"
    assert classify_failure_code("DURABLE_JOB_FAILED:content rejected") == "PROVIDER_REJECTED"
    assert classify_failure_code("DURABLE_JOB_EXPIRED:gone") == "PROVIDER_EXPIRED"
    assert classify_failure_code("DURABLE_DOWNLOAD_HTTP_500") == "DOWNLOAD_ERROR"
    assert classify_failure_code("ENDPOINT_ADMISSION_BLOCKED:duration") == "CAPABILITY_BLOCKED"
    assert classify_failure_code("something else") == "PROVIDER_ERROR"


def test_task_failure_evidence_is_safe_and_actionable() -> None:
    """E09: repair action + desensitized reason surface on the task."""

    from hevi.tasks.task_service import TaskService

    evidence = TaskService._normalize_task_failure(
        "DURABLE_JOB_FAILED: api_key=SECRET123 content rejected at provider",
        __import__("uuid").uuid4(),
    )
    assert evidence["normalized_code"] == "PROVIDER_REJECTED"
    assert "SECRET123" not in evidence["safe_message"]
    assert evidence["repair_action"]["target_id"]  # always an actionable repair target


@pytest.mark.asyncio
async def test_adapter_failure_writes_normalized_evidence() -> None:
    """E09: real adapter failure path persists normalized failure evidence."""

    from hevi.production.adapters import ProductionAdapterRegistry
    from hevi.tasks.task_service import TaskService

    repo = DictRepository()
    adapters = ProductionAdapterRegistry()

    async def failing_adapter(task, pool):
        return {
            **task,
            "status": "failed",
            "error": {"message": "provider failure: quota exhausted"},
        }

    adapters.register("explainer", failing_adapter)
    service = TaskService(repo, production_adapters=adapters)  # type: ignore[arg-type]
    task_id = repo.seed(
        {
            "status": "running",
            "status_source": None,
            "config_json": {"production_source": "explainer"},
        }
    )
    task = await repo.get_task(task_id)
    assert task is not None
    result = await service._run_adapter_task(task)
    assert result["status"] == "failed"
    stored = await repo.get_task(task_id)
    assert stored is not None
    failure = stored["config_json"]["failure"]
    assert failure["normalized_code"] == "PROVIDER_ERROR"
    assert failure["repair_action"]["target_id"] == str(task_id)
    assert stored["error"]


@pytest.mark.asyncio
async def test_call_row_reconciliation_scenarios(tmp_path, monkeypatch) -> None:
    """N06: pending rows terminalize from execution/task evidence, idempotently."""

    from hevi.creative.layer4.authority_stores import CallLedgerStore
    from hevi.creative.layer4.usage_ledger import begin_call

    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    from hevi.tasks.durable_execution import apply_execution_event, begin_execution

    repo = DictRepository()
    service = TaskService(repo)  # type: ignore[arg-type]
    store = CallLedgerStore()

    # A: pending + active execution -> stays ACTIVE (still pending)
    active_id = repo.seed({"status": "running", "config_json": {}})
    active_task = await repo.get_task(active_id)
    assert active_task is not None
    cfg, _r, _a = begin_execution(
        {},
        provider="p",
        endpoint="e",
        model="m",
        request={"x": 1},
        production_revision="r",
        target_artifact_id="t",
        idempotency_key="k1",
    )
    cfg, _r = apply_execution_event(cfg, {"kind": "submitted", "provider_job_id": "job-a"})
    await repo.update_task(active_id, {"config_json": cfg})
    call_a = begin_call(
        project_ref="p", provider="p", model="m", operation_type="generate", task_ref=str(active_id)
    )
    store.append(call_a.model_dump(mode="json"))

    # B: pending + completed execution (remote success + download) -> RECONCILED
    done_id = repo.seed({"status": "completed", "config_json": {}})
    cfg2, _r2, _a2 = begin_execution(
        {},
        provider="p",
        endpoint="e",
        model="m",
        request={"x": 2},
        production_revision="r",
        target_artifact_id="t2",
        idempotency_key="k2",
    )
    cfg2, _r2 = apply_execution_event(cfg2, {"kind": "submitted", "provider_job_id": "job-b"})
    cfg2, _r2 = apply_execution_event(
        cfg2, {"kind": "remote_success", "remote_artifact_url": "https://cdn/b"}
    )
    cfg2, _r2 = apply_execution_event(
        cfg2,
        {
            "kind": "download_complete",
            "local_artifact_path": "/tmp/b",
            "checksum": "b",
            "actual_cost": 1.5,
        },
    )
    await repo.update_task(done_id, {"config_json": cfg2})
    call_b = begin_call(
        project_ref="p", provider="p", model="m", operation_type="generate", task_ref=str(done_id)
    )
    store.append(call_b.model_dump(mode="json"))

    # C: pending + failed execution -> FAILED
    fail_id = repo.seed({"status": "failed", "config_json": {}})
    cfg3, _r3, _a3 = begin_execution(
        {},
        provider="p",
        endpoint="e",
        model="m",
        request={"x": 3},
        production_revision="r",
        target_artifact_id="t3",
        idempotency_key="k3",
    )
    cfg3, _r3 = apply_execution_event(cfg3, {"kind": "submitted", "provider_job_id": "job-c"})
    cfg3, _r3 = apply_execution_event(cfg3, {"kind": "remote_failed", "error": "content rejected"})
    await repo.update_task(fail_id, {"config_json": cfg3})
    call_c = begin_call(
        project_ref="p", provider="p", model="m", operation_type="generate", task_ref=str(fail_id)
    )
    store.append(call_c.model_dump(mode="json"))

    # D: pending + task missing -> ABANDONED
    call_d = begin_call(
        project_ref="p",
        provider="p",
        model="m",
        operation_type="generate",
        task_ref=str(uuid.uuid4()),
    )
    store.append(call_d.model_dump(mode="json"))
    # E: pending + already-billed call (terminal) -> untouched
    call_e = begin_call(
        project_ref="p", provider="p", model="m", operation_type="generate", task_ref=""
    )
    from hevi.creative.layer4.usage_ledger import complete_call

    store.append(complete_call(call_e, actual_cost=2.0).model_dump(mode="json"))

    first = await service.reconcile_call_rows(limit=100)
    assert first["pending"] == 4
    assert first["changed"] == 3  # B->reconciled, C->failed, D->abandoned; A stays active

    rows, _ = store.list_records(limit=100)
    by_id = {r["call_id"]: r for r in rows}
    assert by_id[str(call_a.call_id)]["status"] == "pending"  # ACTIVE preserved
    assert by_id[str(call_b.call_id)]["status"] == "reconciled"
    assert by_id[str(call_b.call_id)]["actual_cost"] == 1.5
    assert by_id[str(call_c.call_id)]["status"] == "failed"
    assert by_id[str(call_c.call_id)]["normalized_error_code"] == "PROVIDER_REJECTED"
    assert by_id[str(call_d.call_id)]["status"] == "abandoned"
    assert by_id[str(call_e.call_id)]["status"] == "succeeded"
    assert by_id[str(call_e.call_id)]["actual_cost"] == 2.0

    # idempotent: second and third runs change nothing, create no rows
    second = await service.reconcile_call_rows(limit=100)
    third = await service.reconcile_call_rows(limit=100)
    assert second["changed"] == 0 and third["changed"] == 0
    rows2, total2 = store.list_records(limit=100)
    assert total2 == len(rows2) == 5
    assert {r["call_id"] for r in rows2} == set(by_id)
    assert by_id[str(call_b.call_id)]["actual_cost"] == 1.5  # cost not doubled


@pytest.mark.asyncio
async def test_reconcile_remote_success_download_pending_stays_active(
    tmp_path, monkeypatch
) -> None:
    """N06: remote success + download recovering is ACTIVE, never SUCCEEDED early."""

    from hevi.creative.layer4.authority_stores import CallLedgerStore
    from hevi.creative.layer4.usage_ledger import begin_call
    from hevi.tasks.durable_execution import apply_execution_event, begin_execution

    monkeypatch.setenv("HEVI_USAGE_DB", str(tmp_path / "usage.db"))
    repo = DictRepository()
    service = TaskService(repo)  # type: ignore[arg-type]
    store = CallLedgerStore()
    task_id = repo.seed({"status": "running", "config_json": {}})
    cfg, _r, _a = begin_execution(
        {},
        provider="p",
        endpoint="e",
        model="m",
        request={"x": 1},
        production_revision="r",
        target_artifact_id="t",
        idempotency_key="k",
    )
    cfg, _r = apply_execution_event(cfg, {"kind": "submitted", "provider_job_id": "job"})
    cfg, _r = apply_execution_event(
        cfg, {"kind": "remote_success", "remote_artifact_url": "https://cdn/x"}
    )
    await repo.update_task(task_id, {"config_json": cfg})
    call = begin_call(
        project_ref="p", provider="p", model="m", operation_type="generate", task_ref=str(task_id)
    )
    store.append(call.model_dump(mode="json"))

    result = await service.reconcile_call_rows(limit=10)
    assert result["changed"] == 0
    rows, _ = store.list_records(limit=10)
    assert rows[0]["status"] == "pending"
    assert rows[0]["actual_cost"] is None  # unknown cost stays unknown, never 0
