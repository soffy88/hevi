"""HEVI P4 - canonical batch scheduler (operations only).

One scheduler for production batches. Dispatches P3 missions per job with
priority + FIFO + aging fairness, concurrency/resource/quota/budget gates,
backpressure, worker leases, pause/resume/cancel, and durable recovery.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.ops.p4_types import (
    BatchBudget,
    OpsMetrics,
    ProductionBatch,
    ProductionJob,
    ProviderQuota,
    ResourceLedger,
    RetryPolicy,
    SLAReport,
    WorkerLease,
)

_STORE_FILENAME = "batch.json"
_CANCEL_FILENAME = "CANCEL"
_PAUSE_FILENAME = "PAUSE"

JobRunner = Callable[[ProductionJob, Path], Coroutine[Any, Any, dict[str, Any]]]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _mem_available_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return float(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return 999.0


def _disk_free_pct(path: Path) -> float:
    usage = shutil.disk_usage(str(path))
    return usage.free / usage.total * 100 if usage.total else 0.0


class _JobNode:
    """Pseudo PlanNode wrapper for ProductionJob to reuse MissionExecutor logic."""
    def __init__(self, job: ProductionJob) -> None:
        self.job = job
        self.kind = "RENDER"
        self.status = job.status
        self.attempts = job.attempts
        self.max_attempts = job.max_attempts
        self.artifact_ids = ()
        self.error = job.error
        self._node_id = job.job_id
        self.dependencies = ()
    def set_status(self, status: str) -> None:
        self.job.set_status(status)
    @property
    def node_id(self) -> str:
        return self._node_id
    @property
    def job_id(self) -> str:
        return self.job.job_id
    def __getattr__(self, name: str) -> Any:
        return getattr(self.job, name)


class BatchStore:
    """Durable file-backed batch store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self.root / _STORE_FILENAME

    def save(self, batch: ProductionBatch) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(batch.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def load(self) -> ProductionBatch | None:
        if not self.path.is_file():
            return None
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        batch = ProductionBatch(batch_id=raw.get("batch_id", ""), priority=int(raw.get("priority", 5)),
                                concurrency_limit=int(raw.get("concurrency_limit", 2)))
        batch.status = raw.get("status", "CREATED")
        batch.revision = int(raw.get("revision", 1))
        bg = raw.get("budget", {})
        batch.budget = BatchBudget(
            max_total_cost_usd=float(bg.get("max_total_cost_usd", 100) or 0),
            max_cost_per_job_usd=float(bg.get("max_cost_per_job_usd", 20) or 0),
            max_cost_per_minute_usd=float(bg.get("max_cost_per_minute_usd", 5) or 0),
            actual_cost_usd=float(bg.get("actual_cost_usd", 0) or 0))
        rp = raw.get("retry_policy", {})
        batch.retry_policy = RetryPolicy(
            max_attempts=int(rp.get("max_attempts", 3)),
            max_provider_retries=int(rp.get("max_provider_retries", 2)),
            max_render_retries=int(rp.get("max_render_retries", 2)),
            max_repair_cycles=int(rp.get("max_repair_cycles", 2)),
            backoff_s=float(rp.get("backoff_s", 5.0)))
        batch.quota_policy = raw.get("quota_policy", {})
        batch.created_at = raw.get("created_at", batch.created_at)
        batch.updated_at = raw.get("updated_at", batch.updated_at)
        for j in raw.get("jobs", []):
            job = ProductionJob(job_id=j.get("job_id", ""), profile_id=j.get("profile_id", ""),
                                topic=j.get("topic", ""), narration=j.get("narration", ""),
                                priority=int(j.get("priority", 5)))
            job.status = j.get("status", "CREATED")
            job.attempts = int(j.get("attempts", 0))
            job.max_attempts = int(j.get("max_attempts", 2))
            job.enqueued_at = j.get("enqueued_at", job.enqueued_at)
            job.started_at = j.get("started_at", "")
            job.finished_at = j.get("finished_at", "")
            job.age_boost = int(j.get("age_boost", 0))
            job.mission_id = j.get("mission_id", "")
            job.mission_dir = j.get("mission_dir", "")
            job.final_mp4 = j.get("final_mp4", "")
            job.delivery_receipt = j.get("delivery_receipt", "")
            job.error = j.get("error", "")
            job.failure_class = j.get("failure_class", "")
            job.estimated_cost_usd = float(j.get("estimated_cost_usd", 2.0) or 0)
            job.actual_cost_usd = float(j.get("actual_cost_usd", 0) or 0)
            job.book_meta = j.get("book_meta")
            job.worker_id = j.get("worker_id", "")
            job.lease_id = j.get("lease_id", "")
            batch.jobs.append(job)
        return batch

    def cancel_requested(self) -> bool:
        return (self.root / _CANCEL_FILENAME).is_file()

    def request_cancel(self) -> None:
        (self.root / _CANCEL_FILENAME).write_text("cancel", encoding="utf-8")

    def paused(self) -> bool:
        return (self.root / _PAUSE_FILENAME).is_file()

    def set_paused(self, paused: bool) -> None:
        flag = self.root / _PAUSE_FILENAME
        if paused:
            flag.write_text("paused", encoding="utf-8")
        elif flag.is_file():
            flag.unlink()


def create_batch(root: Path, jobs: list[ProductionJob], priority: int = 5,
                 concurrency_limit: int = 2, budget_usd: float = 100.0) -> tuple[ProductionBatch, BatchStore]:
    store = BatchStore(root)
    batch = ProductionBatch(batch_id=f"batch-{uuid.uuid4().hex[:8]}", priority=priority,
                            concurrency_limit=concurrency_limit,
                            budget=BatchBudget(max_total_cost_usd=budget_usd))
    for job in jobs:
        job.status = "QUEUED"
        batch.jobs.append(job)
    store.save(batch)
    return batch, store


def classify_error(error: str) -> str:
    e = (error or "").lower()
    if any(k in e for k in ("timeout", "temporarily", "connection", "rate limit", "429", "503")):
        return "TRANSIENT"
    if any(k in e for k in ("memory", "oom", "disk", "no space", "resource")):
        return "RESOURCE"
    if any(k in e for k in ("provider", "quota", "credential", "auth")):
        return "PROVIDER"
    if any(k in e for k in ("unverified", "source", "provenance", "script")):
        return "CONTENT"
    if any(k in e for k in ("qa", "quality", "gate", "blocked artifact")):
        return "QA"
    return "PERMANENT"


class Scheduler:
    """Canonical batch scheduler with fairness, caps, leases, and recovery."""

    def __init__(self, store: BatchStore, resources: ResourceLedger | None = None,
                 quota: ProviderQuota | None = None, worker_id: str = "") -> None:
        self.store = store
        self.resources = resources or ResourceLedger()
        self.quota = quota or ProviderQuota()
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.leases: dict[str, WorkerLease] = {}
        self.metrics = OpsMetrics()
        self.sla: dict[str, SLAReport] = {}
        self.max_observed_concurrency = 0
        self._running = 0

    # gate
    def backpressure(self, root: Path) -> tuple[bool, str]:
        if _disk_free_pct(root) < 5.0:
            return True, "disk critically low"
        if _mem_available_gb() < 0.75:
            return True, "RAM pressure"
        if self._running >= max(1, self.resources.render_slots + self.resources.cpu_slots):
            return True, "render saturation"
        return False, ""

    def pick_next(self, batch: ProductionBatch) -> ProductionJob | None:
        queued = [j for j in batch.jobs if j.status == "QUEUED"]
        if not queued:
            return None
        for job in queued:
            job.age_boost = min(job.age_boost, 10)
        queued.sort(key=lambda j: j.effective_priority())
        return queued[0]

    def age_queues(self, batch: ProductionBatch, dispatched_id: str) -> None:
        for job in batch.jobs:
            if job.status == "QUEUED" and job.job_id != dispatched_id:
                job.age_boost = min(job.age_boost + 1, 10)

    # leases
    def issue_lease(self, job: ProductionJob, ttl_s: int = 600) -> WorkerLease:
        lease = WorkerLease(worker_id=self.worker_id, lease_id=f"lease-{uuid.uuid4().hex[:8]}",
                            job_id=job.job_id)
        try:
            exp = datetime.now(UTC).timestamp() + ttl_s
            lease.expires_at = datetime.fromtimestamp(exp, UTC).isoformat().replace("+00:00", "Z")
        except ValueError:
            lease.expires_at = ""
        self.leases[job.job_id] = lease
        job.worker_id = lease.worker_id
        job.lease_id = lease.lease_id
        return lease

    def heartbeat(self, job_id: str) -> None:
        lease = self.leases.get(job_id)
        if lease is not None:
            lease.last_heartbeat = _now()

    def reap_orphans(self, batch: ProductionBatch, live_workers: set[str]) -> list[str]:
        now = _now()
        reaped = []
        for job in batch.jobs:
            if job.status != "RUNNING":
                continue
            lease = self.leases.get(job.job_id)
            gone = job.worker_id not in live_workers
            expired = lease.expired(now) if lease else True
            if gone and expired:
                job.status = "QUEUED"
                job.lease_id = ""
                job.worker_id = ""
                reaped.append(job.job_id)
        return reaped

    async def run(self, batch: ProductionBatch, runner: JobRunner,
                  live_workers: set[str] | None = None) -> ProductionBatch:
        live = live_workers if live_workers is not None else {self.worker_id}
        self.reap_orphans(batch, live)
        if batch.status == "QUEUED":
            batch.set_status("RUNNING")
        self.store.save(batch)

        while True:
            if self.store.cancel_requested():
                for job in batch.jobs:
                    if job.status in ("QUEUED", "PAUSED"):
                        job.set_status("CANCELLED")
                batch.set_status("CANCELLED")
                self.store.save(batch)
                return batch
            if self.store.paused():
                if batch.status == "RUNNING":
                    batch.set_status("PAUSED")
                    self.store.save(batch)
                await asyncio.sleep(5)
                continue
            if batch.status == "PAUSED":
                batch.set_status("RUNNING")
                self.store.save(batch)
            # Backpressure gate: if active, skip collecting new jobs this iteration
            bp_active, _ = self.backpressure(self.store.root)
            # Collect up to concurrency_limit ready jobs
            ready = []
            if not bp_active:
                for _ in range(batch.concurrency_limit):
                    nxt = self.pick_next(batch)
                    if nxt is None:
                        break
                    # Budget gate before dispatch
                    ok, _ = batch.budget.check_job(nxt.estimated_cost_usd)
                    if not ok:
                        nxt.status = "BLOCKED"
                        nxt.error = "BUDGET_BLOCKED"
                        self.store.save(batch)
                        continue
                    if not self.resources.reserve("render"):
                        continue
                    qok, _ = self.quota.acquire(_now())
                    if not qok:
                        self.resources.release("render")
                        nxt.status = "BLOCKED"
                        nxt.error = "PROVIDER_QUOTA"
                        self.store.save(batch)
                        continue
                    nxt.set_status("RUNNING")
                    self.issue_lease(nxt)
                    self.age_queues(batch, nxt.job_id)
                    self.store.save(batch)
                    ready.append(nxt)

            if not ready:
                running = any(j.status == "RUNNING" for j in batch.jobs)
                if not running:
                    break
                await asyncio.sleep(1)
                continue

            # Dispatch all ready jobs concurrently
            async def _run_job_with_sem(job: ProductionJob) -> None:
                async with asyncio.Semaphore(max(1, batch.concurrency_limit)):
                    await self._run_job(batch, job, runner)

            await asyncio.gather(*(_run_job_with_sem(j) for j in ready))
            self.store.save(batch)

        self._finalize(batch)
        self.store.save(batch)
        return batch

    async def _run_job(self, batch: ProductionBatch, job: ProductionJob, runner: JobRunner) -> None:
        t0 = time.monotonic()
        sla = SLAReport(job_id=job.job_id)
        try:
            started = datetime.fromisoformat(job.enqueued_at.replace("Z", "+00:00")).timestamp()
            sla.queue_wait_s = round(max(0.0, time.monotonic() - started), 1)
        except ValueError:
            pass
        attempts = 0
        self._running += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self._running)
        try:
            while attempts < max(1, job.max_attempts):
                attempts += 1
                job.attempts = attempts
                self.heartbeat(job.job_id)
                try:
                    evidence = await runner(job, self.store.root / job.job_id)
                    job.actual_cost_usd = float(evidence.get("actual_cost_usd", 0.0))
                    batch.budget.actual_cost_usd += job.actual_cost_usd
                    job.final_mp4 = str(evidence.get("final_mp4", ""))
                    job.delivery_receipt = str(evidence.get("delivery_receipt", ""))
                    job.mission_id = str(evidence.get("mission_id", ""))

                    job.set_status("COMPLETED")
                    self.metrics.completed += 1
                    self.metrics.delivered += 1
                    self.metrics.total_cost_usd += job.actual_cost_usd
                    self.metrics.total_video_s += float(evidence.get("duration_s", 0.0))
                    break
                except asyncio.CancelledError:
                    job.set_status("CANCELLED")
                    break
                except Exception as exc:
                    kind = classify_error(str(exc))
                    job.failure_class = kind
                    if kind in ("TRANSIENT", "RESOURCE"):
                        self.metrics.retries += 1
                        if attempts >= max(1, job.max_attempts):
                            job.status = "FAILED"
                            job.error = f"RETRY_EXHAUSTED: {exc}"[:500]
                            self.metrics.failed += 1
                            break
                        await asyncio.sleep(batch.retry_policy.backoff_s)
                        continue
                    if kind == "PROVIDER":
                        self.metrics.provider_failures += 1
                        job.status = "BLOCKED"
                        job.error = str(exc)[:500]
                        break
                    if kind in ("CONTENT", "QA"):
                        self.metrics.render_failures += 1
                        job.status = "FAILED"
                        job.error = str(exc)[:500]
                        break
                    job.status = "FAILED"
                    job.error = str(exc)[:500]
                    self.metrics.failed += 1
                    break
        finally:
            self._running -= 1
            self.max_observed_concurrency = max(self.max_observed_concurrency, self._running)
            self.resources.release("render")
        sla.production_duration_s = round(time.monotonic() - t0, 1)
        sla.total_latency_s = round(sla.queue_wait_s + sla.production_duration_s, 1)
        self.sla[job.job_id] = sla

    def _finalize(self, batch: ProductionBatch) -> None:
        terminal = all(j.status in ("COMPLETED", "FAILED", "CANCELLED", "BLOCKED") for j in batch.jobs)
        if not terminal:
            return
        if all(j.status == "COMPLETED" for j in batch.jobs):
            batch.set_status("COMPLETED")
        elif any(j.status == "FAILED" for j in batch.jobs):
            batch.set_status("FAILED")
        else:
            batch.set_status("CANCELLED")

    def metrics_view(self, batch: ProductionBatch) -> dict[str, Any]:
        m = self.metrics.to_dict()
        m.update({
            "queue_depth": sum(1 for j in batch.jobs if j.status == "QUEUED"),
            "running_jobs": sum(1 for j in batch.jobs if j.status == "RUNNING"),
            "blocked_jobs": sum(1 for j in batch.jobs if j.status == "BLOCKED"),
            "completed_jobs": sum(1 for j in batch.jobs if j.status == "COMPLETED"),
            "failed_jobs": sum(1 for j in batch.jobs if j.status == "FAILED"),
            "max_observed_concurrency": self.max_observed_concurrency,
            "leases": len(self.leases),
        })
        return m

    def dashboard(self, batch: ProductionBatch) -> dict[str, Any]:
        return {
            "batch_id": batch.batch_id, "status": batch.status,
            "progress": self.metrics_view(batch),
            "budget": batch.budget.to_dict(),
            "quota": self.quota.to_dict(),
            "resources": self.resources.to_dict(),
            "jobs": [{"job_id": j.job_id, "profile": j.profile_id, "status": j.status,
                      "priority": j.priority, "attempts": j.attempts,
                      "worker": j.worker_id, "error": j.error[:120],
                      "final": bool(j.final_mp4)} for j in batch.jobs],
            "sla": {k: v.to_dict() for k, v in self.sla.items()},
            "blockers": [j.job_id for j in batch.jobs if j.status in ("BLOCKED", "FAILED")],
        }


__all__ = [
    "BatchStore",
    "Scheduler",
    "classify_error",
    "create_batch",
]