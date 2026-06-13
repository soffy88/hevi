"""P10.A-B5 monitoring tests — 10 metrics, middleware, /metrics endpoint."""

from httpx import AsyncClient
from prometheus_client import REGISTRY

import hevi.monitoring.metrics as m


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    """Return current registry sample value, defaulting to 0.0 if not yet emitted."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ── 1. Metric definitions ─────────────────────────────────────────────────────

def test_ten_metrics_defined() -> None:
    """All 10 metric names exist on the metrics module."""
    names = [
        "http_requests_total",
        "http_request_duration_seconds",
        "http_requests_in_progress",
        "video_generation_total",
        "video_generation_duration_seconds",
        "video_generation_in_progress",
        "credits_consumed_total",
        "provider_api_calls_total",
        "provider_api_latency_seconds",
        "app_info",
    ]
    for name in names:
        assert hasattr(m, name), f"Missing metric: {name}"


# ── 2. /metrics endpoint ──────────────────────────────────────────────────────

async def test_metrics_endpoint_returns_200(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200


async def test_metrics_endpoint_content_type_is_plain_text(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert "text/plain" in response.headers["content-type"]


async def test_metrics_body_contains_all_ten_names(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    body = response.text
    expected = [
        "http_requests_total",
        "http_request_duration_seconds",
        "http_requests_in_progress",
        "video_generation_total",
        "video_generation_duration_seconds",
        "video_generation_in_progress",
        "credits_consumed_total",
        "provider_api_calls_total",
        "provider_api_latency_seconds",
        "app_info",
    ]
    for name in expected:
        assert name in body, f"/metrics body missing: {name}"


# ── 3. Middleware counter / histogram / gauge ─────────────────────────────────

async def test_request_counter_increments(client: AsyncClient) -> None:
    labels = {"method": "GET", "path": "/api/health", "status": "200"}
    before = _sample("http_requests_total", labels)
    await client.get("/api/health")
    after = _sample("http_requests_total", labels)
    assert after == before + 1.0


async def test_duration_histogram_count_increments(client: AsyncClient) -> None:
    labels = {"method": "GET", "path": "/api/health"}
    before = _sample("http_request_duration_seconds_count", labels)
    await client.get("/api/health")
    after = _sample("http_request_duration_seconds_count", labels)
    assert after == before + 1.0


async def test_in_progress_gauge_is_zero_after_request(client: AsyncClient) -> None:
    await client.get("/api/health")
    assert _sample("http_requests_in_progress") == 0.0


# ── 4. Path template — no label cardinality explosion ─────────────────────────

async def test_path_label_uses_route_template(client: AsyncClient) -> None:
    """Static route /api/health: template == actual path; label must NOT be a raw URL."""
    await client.get("/api/health")
    val = _sample(
        "http_requests_total",
        {"method": "GET", "path": "/api/health", "status": "200"},
    )
    assert val >= 1.0


# ── 5. Business / provider metric interfaces ──────────────────────────────────

def test_video_metrics_labels_accessible() -> None:
    """Business metrics are callable with expected label sets."""
    m.video_generation_total.labels(provider="ltx2", duration_archetype="5s", status="success")
    m.video_generation_duration_seconds.labels(provider="ltx2", duration_archetype="5s")
    m.video_generation_in_progress.inc()
    m.video_generation_in_progress.dec()
    m.credits_consumed_total.labels(user_tier="pro")


def test_provider_metrics_labels_accessible() -> None:
    """Provider metrics are callable with expected label sets."""
    m.provider_api_calls_total.labels(provider="ltx2", status="ok")
    m.provider_api_calls_total.labels(provider="wan", status="error")
    m.provider_api_latency_seconds.labels(provider="vibevoice")
    m.provider_api_latency_seconds.labels(provider="duix")
