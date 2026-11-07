"""circuit_breaker_check — 熔断器状态评估.

Pure algorithm oskill — no external I/O.
Evaluates whether a circuit breaker should open, half-open, or remain closed
based on error rates, latency thresholds, and rolling window statistics.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreakerResult(BaseModel):
    state: CircuitState
    should_trip: bool
    recovery_possible: bool
    error_rate: float
    p99_latency_ms: float | None
    window_samples: int
    reasons: list[str]


_DEFAULT_THRESHOLDS = {
    "error_rate_open": 0.5,  # trip at ≥50% error rate
    "error_rate_half_open": 0.1,  # allow recovery below 10%
    "latency_p99_open_ms": 5000,  # trip if p99 > 5s
    "min_samples": 5,  # need ≥5 samples before tripping
}


def circuit_breaker_check(
    *,
    samples: list[dict[str, Any]],
    current_state: CircuitState = "closed",
    thresholds: dict[str, float] | None = None,
) -> CircuitBreakerResult:
    """熔断器状态评估 — 根据滑动窗口样本决定是否熔断.

    Composition note: pure algorithm. Feed results from oprim health checks
    as samples. Used by TriageEngine and custom omodul modules.

    Args:
        samples: 样本列表, 每条含:
                 - "success" (bool): 请求是否成功
                 - "latency_ms" (float, optional): 响应延迟
        current_state: 当前熔断器状态 (closed/open/half_open)
        thresholds: 阈值覆盖 (error_rate_open, error_rate_half_open,
                    latency_p99_open_ms, min_samples)

    Returns:
        CircuitBreakerResult
    """
    t = {**_DEFAULT_THRESHOLDS, **(thresholds or {})}
    reasons: list[str] = []

    n = len(samples)
    if n == 0:
        return CircuitBreakerResult(
            state=current_state,
            should_trip=False,
            recovery_possible=current_state == "open",
            error_rate=0.0,
            p99_latency_ms=None,
            window_samples=0,
            reasons=["No samples — keeping current state"],
        )

    # Compute error rate
    failures = sum(1 for s in samples if not s.get("success", True))
    error_rate = failures / n

    # Compute p99 latency
    latencies = sorted([float(s["latency_ms"]) for s in samples if "latency_ms" in s])
    p99: float | None = None
    if latencies:
        idx = max(0, int(len(latencies) * 0.99) - 1)
        p99 = latencies[idx]

    should_trip = False
    recovery_possible = False
    new_state = current_state

    if n < int(t["min_samples"]):
        reasons.append(f"Insufficient samples ({n} < {int(t['min_samples'])}) — no state change")
        return CircuitBreakerResult(
            state=current_state,
            should_trip=False,
            recovery_possible=False,
            error_rate=round(error_rate, 4),
            p99_latency_ms=round(p99, 2) if p99 is not None else None,
            window_samples=n,
            reasons=reasons,
        )

    # State machine
    if current_state == "closed":
        if error_rate >= t["error_rate_open"]:
            should_trip = True
            new_state = "open"
            reasons.append(
                f"Error rate {error_rate:.1%} ≥ threshold {t['error_rate_open']:.1%} → trip"
            )
        elif p99 is not None and p99 >= t["latency_p99_open_ms"]:
            should_trip = True
            new_state = "open"
            reasons.append(
                f"P99 latency {p99:.0f}ms ≥ threshold {t['latency_p99_open_ms']:.0f}ms → trip"
            )
        else:
            reasons.append("Within thresholds — circuit remains closed")

    elif current_state == "open":
        if error_rate < t["error_rate_half_open"]:
            recovery_possible = True
            new_state = "half_open"
            reasons.append(f"Error rate {error_rate:.1%} < recovery threshold → half-open")
        else:
            reasons.append(f"Error rate {error_rate:.1%} still elevated — circuit remains open")

    elif current_state == "half_open":
        if error_rate >= t["error_rate_open"]:
            should_trip = True
            new_state = "open"
            reasons.append(f"Re-trip: error rate {error_rate:.1%} spiked during probe → open")
        elif error_rate < t["error_rate_half_open"]:
            new_state = "closed"
            reasons.append(f"Recovery confirmed: error rate {error_rate:.1%} → closed")
        else:
            reasons.append("Half-open probe inconclusive — staying half-open")

    return CircuitBreakerResult(
        state=new_state,
        should_trip=should_trip,
        recovery_possible=recovery_possible,
        error_rate=round(error_rate, 4),
        p99_latency_ms=round(p99, 2) if p99 is not None else None,
        window_samples=n,
        reasons=reasons,
    )
