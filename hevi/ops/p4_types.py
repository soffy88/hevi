"""HEVI P4 — Production Operations canonical types.

Batch → Job → Mission(P3) hierarchy with durable scheduling state,
quotas, budgets, leases, SLA, metrics, and retention policy.
Scheduling/operations only; all media work stays in P0–P3.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class BatchStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class JobStatus(StrEnum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


_BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"QUEUED", "CANCELLED"}),
    "QUEUED": frozenset({"RUNNING", "PAUSED", "CANCELLED"}),
    "RUNNING": frozenset({"DEGRADED", "PARTIAL", "COMPLETED", "FAILED", "PAUSED", "CANCELLED"}),
    "DEGRADED": frozenset({"RUNNING", "PARTIAL", "COMPLETED", "FAILED", "PAUSED", "CANCELLED"}),
    "PARTIAL": frozenset({"PARTIAL"}),
    "COMPLETED": frozenset({"COMPLETED"}),
    "FAILED": frozenset({"FAILED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
    "PAUSED": frozenset({"QUEUED", "RUNNING", "CANCELLED"}),
}

_JOB_TRANSITIONS: dict[str, frozenset[str]] = {
    "CREATED": frozenset({"QUEUED", "CANCELLED"}),
    "QUEUED": frozenset({"RUNNING", "PAUSED", "CANCELLED"}),
    "RUNNING": frozenset({"BLOCKED", "FAILED", "COMPLETED", "PAUSED", "CANCELLED"}),
    "BLOCKED": frozenset({"QUEUED", "RUNNING", "FAILED", "CANCELLED"}),
    "FAILED": frozenset({"QUEUED", "FAILED"}),
    "COMPLETED": frozenset({"COMPLETED"}),
    "CANCELLED": frozenset({"CANCELLED"}),
    "PAUSED": frozenset({"QUEUED", "RUNNING", "CANCELLED"}),
}


def _check(table: dict[str, frozenset[str]], previous: str, current: str, kind: str) -> None:
    if previous == current:
        return
    allowed = table.get(previous)
    if allowed is None or current not in allowed:
        raise ValueError(f"invalid {kind} transition: {previous!r} -> {current!r}")


def validate_batch_transition(previous: str, current: str) -> None:
    _check(_BATCH_TRANSITIONS, previous, current, "batch")


def validate_job_transition(previous: str, current: str) -> None:
    _check(_JOB_TRANSITIONS, previous, current, "job")


@dataclass
class RetryPolicy:
    max_attempts: int = 3
    max_provider_retries: int = 2
    max_render_retries: int = 2
    max_repair_cycles: int = 2
    backoff_s: float = 5.0


@dataclass
class BatchBudget:
    max_total_cost_usd: float = 100.0
    max_cost_per_job_usd: float = 20.0
    max_cost_per_minute_usd: float = 5.0
    actual_cost_usd: float = 0.0

    @property
    def remaining_usd(self) -> float:
        return self.max_total_cost_usd - self.actual_cost_usd

    def check_job(self, estimated: float) -> tuple[bool, str]:
        if estimated > self.max_cost_per_job_usd:
            return False, "BUDGET_BLOCKED"
        if self.actual_cost_usd + estimated > self.max_total_cost_usd:
            return False, "BUDGET_BLOCKED"
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProviderQuota:
    requests_per_min: int = 30
    requests_per_day: int = 5000
    max_concurrent: int = 4
    used_today: int = 0
    window_requests: list[str] = field(default_factory=list)

    def acquire(self, now_iso: str) -> tuple[bool, str]:
        from datetime import datetime as _dt
        now = _dt.fromisoformat(now_iso.replace("Z", "+00:00"))
        cutoff = (now.timestamp() - 60)
        self.window_requests = [t for t in self.window_requests
                                if _dt.fromisoformat(t.replace("Z", "+00:00")).timestamp() >= cutoff]
        if len(self.window_requests) >= self.requests_per_min:
            return False, "PROVIDER_QUOTA_THROTTLE"
        if self.used_today >= self.requests_per_day:
            return False, "PROVIDER_QUOTA_BLOCKED"
        self.window_requests.append(now_iso)
        self.used_today += 1
        return True, ""

    def to_dict(self) -> dict[str, Any]:
        return {"requests_per_min": self.requests_per_min,
                "requests_per_day": self.requests_per_day,
                "max_concurrent": self.max_concurrent,
                "used_today": self.used_today,
                "window_count": len(self.window_requests)}


@dataclass
class ResourceLedger:
    cpu_slots: int = 2
    render_slots: int = 2
    tts_slots: int = 2
    used_cpu: int = 0
    used_render: int = 0
    used_tts: int = 0
    disk_threshold_pct: float = 95.0

    def reserve(self, kind: str) -> bool:
        if kind == "render" and self.used_render < self.render_slots:
            self.used_render += 1
            return True
        if kind == "tts" and self.used_tts < self.tts_slots:
            self.used_tts += 1
            return True
        if kind == "cpu" and self.used_cpu < self.cpu_slots:
            self.used_cpu += 1
            return True
        return False

    def release(self, kind: str) -> None:
        if kind == "render":
            self.used_render = max(0, self.used_render - 1)
        elif kind == "tts":
            self.used_tts = max(0, self.used_tts - 1)
        elif kind == "cpu":
            self.used_cpu = max(0, self.used_cpu - 1)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerLease:
    worker_id: str
    lease_id: str
    job_id: str
    expires_at: str = ""
    last_heartbeat: str = field(default_factory=_now)

    def expired(self, now_iso: str) -> bool:
        return bool(self.expires_at) and now_iso >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionJob:
    job_id: str
    profile_id: str = ""
    topic: str = ""
    narration: str = ""
    priority: int = 5  # 0 highest
    status: str = "CREATED"
    attempts: int = 0
    max_attempts: int = 2
    enqueued_at: str = field(default_factory=_now)
    started_at: str = ""
    finished_at: str = ""
    age_boost: int = 0
    mission_id: str = ""
    mission_dir: str = ""
    final_mp4: str = ""
    delivery_receipt: str = ""
    error: str = ""
    failure_class: str = ""
    estimated_cost_usd: float = 2.0
    actual_cost_usd: float = 0.0
    book_meta: dict[str, Any] | None = None
    segments: int = 1
    worker_id: str = ""
    lease_id: str = ""

    def set_status(self, status: str) -> None:
        validate_job_transition(self.status, status)
        self.status = status
        if status == "RUNNING" and not self.started_at:
            self.started_at = _now()
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            self.finished_at = _now()

    def effective_priority(self) -> tuple[int, str]:
        return (self.priority - self.age_boost, self.enqueued_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductionBatch:
    batch_id: str
    jobs: list[ProductionJob] = field(default_factory=list)
    priority: int = 5
    concurrency_limit: int = 2
    status: str = "CREATED"
    revision: int = 1
    budget: BatchBudget = field(default_factory=BatchBudget)
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    quota_policy: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def set_status(self, status: str) -> None:
        validate_batch_transition(self.status, status)
        self.status = status
        self.updated_at = _now()

    def job(self, job_id: str) -> ProductionJob | None:
        return next((j for j in self.jobs if j.job_id == job_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {"batch_id": self.batch_id,
                "jobs": [j.to_dict() for j in self.jobs],
                "priority": self.priority, "concurrency_limit": self.concurrency_limit,
                "status": self.status, "revision": self.revision,
                "budget": self.budget.to_dict(),
                "retry_policy": asdict(self.retry_policy),
                "quota_policy": self.quota_policy,
                "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass
class SLAReport:
    job_id: str
    queue_wait_s: float = 0.0
    production_duration_s: float = 0.0
    delivery_duration_s: float = 0.0
    total_latency_s: float = 0.0
    breached: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpsMetrics:
    queued: int = 0
    running: int = 0
    blocked: int = 0
    completed: int = 0
    failed: int = 0
    retries: int = 0
    repairs: int = 0
    provider_failures: int = 0
    render_failures: int = 0
    delivered: int = 0
    total_cost_usd: float = 0.0
    total_video_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["cost_per_video_minute"] = (self.total_cost_usd / (self.total_video_s / 60)
                                      if self.total_video_s > 0 else 0.0)
        return d


@dataclass
class RetentionPolicy:
    temp_ttl_days: int = 7
    cache_ttl_days: int = 30
    keep_final: bool = True
    keep_audit: bool = True

    def classify(self, path: str, refs: tuple[str, ...] = ()) -> str:
        p = path.lower()
        if "delivery_final" in p or "final_timeline" in p:
            return "FINAL"
        if "mission.json" in p or "provenance" in p or "report" in p:
            return "AUDIT"
        if "tts_master" in p or "subtitles" in p:
            return "INTERMEDIATE"
        if ".venv" in p or "node_modules" in p:
            return "CACHE"
        return "TEMP"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


P4_GATES = (
    "QUEUE_SCHEDULER",
    "QUEUE_FAIRNESS",
    "PRIORITY_SCHEDULING",
    "CONCURRENCY_CONTROL",
    "RESOURCE_MANAGER",
    "QUEUE_BACKPRESSURE",
    "PROVIDER_QUOTA",
    "COST_CONTROL",
    "DURATION_CONTROL",
    "LONG_FORM_CONTINUITY",
    "INCREMENTAL_ASSEMBLY",
    "RETRY_CONTROL",
    "WORKER_LEASE",
    "ORPHAN_RECOVERY",
    "BATCH_RECOVERY",
    "PAUSE_RESUME",
    "BATCH_CANCEL",
    "DELIVERY_RUNTIME",
    "DELIVERY_IDEMPOTENCY",
    "EDITABLE_DELIVERY",
    "SLA_OBSERVABILITY",
    "DISK_GUARD",
    "JOB_ISOLATION",
)

ADVERSARIAL_P4_GATES = tuple(f"CASE_P4_{i}" for i in (
    "1_CONCURRENCY_CAP", "2_QUOTA_THROTTLE", "3_NO_STARVATION", "4_LEASE_RECOVERY",
    "5_BATCH_RECOVERY", "6_BACKPRESSURE", "7_INCREMENTAL", "8_BOUNDED_RETRY",
    "9_NO_INFINITE_RETRY", "10_DELIVERY_IDEMPOTENT", "11_CLEAN_CANCEL",
    "12_PAUSE_RESUME", "13_JOB_ISOLATION", "14_BUDGET_BLOCKED",
    "15_DURATION_ERROR", "16_ORPHAN_RECOVERED"))

__all__ = [
    "ADVERSARIAL_P4_GATES",
    "P4_GATES",
    "BatchBudget",
    "BatchStatus",
    "JobStatus",
    "OpsMetrics",
    "ProductionBatch",
    "ProductionJob",
    "ProviderQuota",
    "ResourceLedger",
    "RetentionPolicy",
    "RetryPolicy",
    "SLAReport",
    "WorkerLease",
    "validate_batch_transition",
    "validate_job_transition",
]
