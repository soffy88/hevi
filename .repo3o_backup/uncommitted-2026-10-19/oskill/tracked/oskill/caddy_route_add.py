"""caddy_route_add — 原子式添加 Caddy 路由并验证健康.

Composition:
    oprim.caddy_route_add_atomic  — 原子更新 Caddy config
    oprim.caddy_admin_reload      — (optional) reload trigger
    oprim.network_http_health     — 验证服务是否可达

Used by AppInstallerEngine as caddy_route_add injection.
"""

from __future__ import annotations

from typing import Any

from oprim import caddy_route_add_atomic
from oprim._network import network_http_health  # v3 not top-level
from pydantic import BaseModel


class CaddyRouteAddResult(BaseModel):
    status: str  # "ok" | "failed"
    routes_total: int | None
    health_check_passed: bool
    health_status_code: int | None
    error: str | None


def caddy_route_add(
    *,
    admin_url: str,
    route: dict[str, Any],
    service_url: str,
    server_name: str = "srv0",
    position: int | None = None,
    health_retries: int = 3,
    health_interval_sec: float = 1.0,
    timeout_sec: int = 10,
) -> CaddyRouteAddResult:
    """原子添加 Caddy 路由 + 服务健康检查.

    Composition: oprim.caddy_route_add_atomic → oprim.network_http_health.
    Designed as AppInstallerEngine caddy_route_add injection.

    Args:
        admin_url: Caddy admin API 地址 (e.g. "http://localhost:2019")
        route: Caddy route dict (含 match/handle/terminal 等字段)
        service_url: 路由添加后要健康检查的服务 URL
        server_name: Caddy server 名称 (默认 "srv0")
        position: 插入位置 (None = 追加)
        health_retries: 健康检查最大重试次数
        health_interval_sec: 健康检查重试间隔
        timeout_sec: 每次 HTTP 请求超时

    Returns:
        CaddyRouteAddResult
    """
    import time

    # Step 1: atomic route insertion
    try:
        add_result = caddy_route_add_atomic(
            admin_url=admin_url,
            server_name=server_name,
            route=route,
            position=position,
            timeout_sec=timeout_sec,
        )
        routes_total = add_result.get("routes_total")
    except Exception as exc:
        return CaddyRouteAddResult(
            status="failed",
            routes_total=None,
            health_check_passed=False,
            health_status_code=None,
            error=f"caddy_route_add_atomic failed: {exc}",
        )

    # Step 2: health check with retries
    last_status: int | None = None
    last_error: str | None = None
    healthy = False

    for attempt in range(max(1, health_retries)):
        try:
            hc = network_http_health(url=service_url, timeout_sec=timeout_sec)
            last_status = hc.status_code
            last_error = hc.error
            if hc.healthy:
                healthy = True
                break
        except Exception as exc:
            last_error = str(exc)
        if attempt < health_retries - 1:
            time.sleep(health_interval_sec)

    return CaddyRouteAddResult(
        status="ok" if healthy else "failed",
        routes_total=routes_total,
        health_check_passed=healthy,
        health_status_code=last_status,
        error=None if healthy else (last_error or "health check failed"),
    )
