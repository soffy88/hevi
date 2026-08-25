"""10 Prometheus metric definitions for hevi v6."""

from prometheus_client import Counter, Gauge, Histogram, Info

# ── HTTP layer ────────────────────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently in progress",
)

# ── Business layer — video generation ────────────────────────────────────────
video_generation_total = Counter(
    "video_generation_total",
    "Total video generation jobs",
    ["provider", "duration_archetype", "status"],
)
video_generation_duration_seconds = Histogram(
    "video_generation_duration_seconds",
    "Video generation duration in seconds",
    ["provider", "duration_archetype"],
)
video_generation_in_progress = Gauge(
    "video_generation_in_progress",
    "Video generation jobs currently in progress",
)
credits_consumed_total = Counter(
    "credits_consumed_total",
    "Total credits consumed",
    ["user_tier"],
)

# ── System ────────────────────────────────────────────────────────────────────
app_info = Info("app", "Application information")
app_info.info({"version": "6.0.0", "name": "hevi"})

# ── Production / execution SLOs ─────────────────────────────────────────────
# Labels in this section are taxonomy values (provider, task class, stage,
# and status), never production or user ids. This keeps Prometheus cardinality
# bounded while the ids remain available in logs and traces.
productions_started_total = Counter(
    "productions_started_total", "Productions accepted for execution", ["source"]
)
productions_completed_total = Counter(
    "productions_completed_total", "Productions reaching a terminal state", ["status"]
)
delivery_outcomes_total = Counter(
    "delivery_outcomes_total", "Production delivery outcomes", ["status"]
)
task_queue_latency_seconds = Histogram(
    "task_queue_latency_seconds",
    "Time from task enqueue to durable claim",
    ["task_class", "resource_class"],
)
task_attempt_duration_seconds = Histogram(
    "task_attempt_duration_seconds",
    "Worker attempt duration",
    ["task_class", "status"],
)
task_retries_total = Counter(
    "task_retries_total", "Task retry and fallback attempts", ["task_class", "reason"]
)
worker_utilization = Gauge(
    "worker_utilization", "Fraction of worker capacity currently active", ["resource_class"]
)
lease_expirations_total = Counter(
    "lease_expirations_total", "Task leases recovered after expiry", ["task_class"]
)

# ── Quality / constraints ───────────────────────────────────────────────────
constraint_coverage_ratio = Gauge(
    "constraint_coverage_ratio", "Fraction of required constraints compiled", ["stage"]
)
quality_gate_outcomes_total = Counter(
    "quality_gate_outcomes_total", "Quality gate outcomes", ["gate", "status"]
)
repair_rounds_total = Counter(
    "repair_rounds_total", "Quality repair rounds", ["stage", "reason"]
)
quality_score_delta = Histogram(
    "quality_score_delta", "Quality score delta after repair", ["stage"]
)

# ── Provider / cost ──────────────────────────────────────────────────────────
provider_outcomes_total = Counter(
    "provider_outcomes_total",
    "Provider call outcomes",
    ["provider", "task_class", "status"],
)
provider_latency_seconds = Histogram(
    "provider_latency_seconds", "Provider call latency", ["provider", "task_class"]
)
provider_cost_usd_total = Counter(
    "provider_cost_usd_total", "Estimated provider spend in USD", ["provider", "task_class"]
)
budget_estimate_error_usd = Histogram(
    "budget_estimate_error_usd", "Absolute estimate versus actual cost error", ["stage"]
)
budget_actual_spend_usd_total = Counter(
    "budget_actual_spend_usd_total", "Settled spend in USD", ["stage"]
)
budget_retakes_total = Counter(
    "budget_retakes_total", "Retake attempts charged to the retake pool", ["stage"]
)

# ── Artifact / realtime operations ──────────────────────────────────────────
artifact_commit_outcomes_total = Counter(
    "artifact_commit_outcomes_total", "Artifact manifest commit outcomes", ["status"]
)
artifact_integrity_outcomes_total = Counter(
    "artifact_integrity_outcomes_total", "Artifact integrity verification outcomes", ["status"]
)
object_store_latency_seconds = Histogram(
    "object_store_latency_seconds", "Object-store operation latency", ["backend", "operation"]
)
artifact_cache_outcomes_total = Counter(
    "artifact_cache_outcomes_total", "Artifact cache hits and misses", ["status"]
)
ws_event_lag_seconds = Histogram(
    "ws_event_lag_seconds", "WebSocket event propagation lag", ["event_type"]
)
outbox_events_total = Counter(
    "outbox_events_total", "Transactional outbox lifecycle events", ["operation", "status"]
)
