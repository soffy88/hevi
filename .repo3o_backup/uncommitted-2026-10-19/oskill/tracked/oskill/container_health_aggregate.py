from concurrent.futures import ThreadPoolExecutor
from typing import Literal, cast

from obase.docker import docker_container_inspect
from oprim import http_health_probe
from pydantic import BaseModel


class CheckResult(BaseModel):
    endpoint: str
    healthy: bool
    response_time_ms: int
    status_code: int | None
    error: str | None


class HealthAggregateResult(BaseModel):
    container_id: str
    overall_status: Literal["healthy", "degraded", "down"]
    failing_checks: list[CheckResult] = []
    passing_checks: list[CheckResult] = []
    aggregate_health_score: float  # passing / total


def container_health_aggregate(
    *,
    container_id: str,
    check_endpoints: list[str],
    docker_host: str = "unix:///var/run/docker.sock",
    timeout_sec: int = 10,
) -> HealthAggregateResult:
    """容器健康聚合 (检查容器 state + N 个 HTTP endpoint)."""
    try:
        inspect_info = docker_container_inspect(container_id=container_id, docker_host=docker_host)
    except Exception:
        return HealthAggregateResult(
            container_id=container_id, overall_status="down", aggregate_health_score=0.0
        )

    if inspect_info.state != "running":
        return HealthAggregateResult(
            container_id=container_id, overall_status="down", aggregate_health_score=0.0
        )

    # Check container health status if available
    container_health_status = inspect_info.health or "none"

    results: list[CheckResult] = []

    def run_probe(url: str) -> CheckResult:
        try:
            probe = http_health_probe(url=url, timeout_sec=timeout_sec)
            return CheckResult(
                endpoint=url,
                healthy=cast(bool, probe["healthy"]),
                response_time_ms=cast(int, probe["elapsed_ms"]),
                status_code=cast(int | None, probe["status_code"]),
                error=cast(str | None, probe.get("error")),
            )
        except Exception as e:
            return CheckResult(
                endpoint=url, healthy=False, response_time_ms=0, status_code=None, error=str(e)
            )

    if check_endpoints:
        with ThreadPoolExecutor(max_workers=len(check_endpoints)) as executor:
            results = list(executor.map(run_probe, check_endpoints))

    passing = [r for r in results if r.healthy]
    failing = [r for r in results if not r.healthy]

    # Internal healthcheck influence
    if container_health_status == "unhealthy":
        failing.append(
            CheckResult(
                endpoint="docker-internal-healthcheck",
                healthy=False,
                response_time_ms=0,
                status_code=None,
                error="Container internal healthcheck failed",
            )
        )

    total_checks = len(results) + (1 if container_health_status == "unhealthy" else 0)

    score: float
    overall_status: Literal["healthy", "degraded", "down"]

    if total_checks == 0:
        overall_status = "healthy"
        score = 1.0
    else:
        score = len(passing) / total_checks
        if len(failing) == 0:
            overall_status = "healthy"
        else:
            overall_status = "degraded"

    return HealthAggregateResult(
        container_id=container_id,
        overall_status=overall_status,
        failing_checks=failing,
        passing_checks=passing,
        aggregate_health_score=score,
    )
