"""verify_health_after_action — 行动后健康检查轮询.

Composition: oprim.network_http_health (polling loop).
Used by AppInstallerEngine as verify_health injection.
"""

from __future__ import annotations

import time

from oprim._network import network_http_health  # v3 not top-level
from pydantic import BaseModel


class HealthVerifyResult(BaseModel):
    service_url: str
    healthy: bool
    attempts: int
    final_status_code: int | None
    elapsed_ms: int
    error: str | None


def verify_health_after_action(
    *,
    service_url: str,
    retries: int = 5,
    interval_seconds: float = 3.0,
    expected_status: int = 200,
    timeout_sec: int = 5,
) -> bool:
    """行动后健康检查 — 轮询 HTTP endpoint 直到健康或超出重试次数.

    Composition note: wraps oprim.network_http_health with retry loop.
    Returns plain bool so it can be used directly as AppInstallerEngine
    verify_health injection (engine expects bool result).

    Detailed result available via verify_health_after_action_detail().

    Args:
        service_url: 健康检查 URL
        retries: 最大重试次数
        interval_seconds: 每次重试间隔 (秒)
        expected_status: 期望的 HTTP 状态码
        timeout_sec: 单次请求超时

    Returns:
        True if healthy within retries, False otherwise
    """
    for _ in range(max(1, retries)):
        try:
            result = network_http_health(url=service_url, timeout_sec=timeout_sec)
            if result.healthy and (result.status_code or 0) == expected_status:
                return True
        except Exception:
            pass
        time.sleep(interval_seconds)
    return False


def verify_health_after_action_detail(
    *,
    service_url: str,
    retries: int = 5,
    interval_seconds: float = 3.0,
    expected_status: int = 200,
    timeout_sec: int = 5,
) -> HealthVerifyResult:
    """verify_health_after_action 的详细版本 — 返回完整 HealthVerifyResult."""
    t0 = time.monotonic()
    last_status: int | None = None
    last_error: str | None = None

    for attempt in range(1, max(1, retries) + 1):
        try:
            result = network_http_health(url=service_url, timeout_sec=timeout_sec)
            last_status = result.status_code
            last_error = result.error
            if result.healthy and (result.status_code or 0) == expected_status:
                return HealthVerifyResult(
                    service_url=service_url,
                    healthy=True,
                    attempts=attempt,
                    final_status_code=last_status,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                    error=None,
                )
        except Exception as e:
            last_error = str(e)
        if attempt < retries:
            time.sleep(interval_seconds)

    return HealthVerifyResult(
        service_url=service_url,
        healthy=False,
        attempts=retries,
        final_status_code=last_status,
        elapsed_ms=int((time.monotonic() - t0) * 1000),
        error=last_error,
    )
