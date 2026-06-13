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

# ── Provider layer — ltx2 / wan / vibevoice / duix ───────────────────────────
provider_api_calls_total = Counter(
    "provider_api_calls_total",
    "Total provider API calls",
    ["provider", "status"],
)
provider_api_latency_seconds = Histogram(
    "provider_api_latency_seconds",
    "Provider API latency in seconds",
    ["provider"],
)

# ── System ────────────────────────────────────────────────────────────────────
app_info = Info("app", "Application information")
app_info.info({"version": "6.0.0", "name": "hevi"})
