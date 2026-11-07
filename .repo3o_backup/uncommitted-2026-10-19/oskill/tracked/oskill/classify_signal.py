"""classify_signal — 信号分类 (infrastructure / application / business / unknown)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

SignalClass = Literal["infrastructure", "application", "business", "security", "unknown"]


class SignalClassification(BaseModel):
    signal_class: SignalClass
    confidence: float
    sub_type: str | None
    reasoning: str


_CLASS_RULES: list[dict[str, Any]] = [
    {
        "class": "infrastructure",
        "keywords": [
            "cpu",
            "memory",
            "ram",
            "disk",
            "inode",
            "network",
            "timeout",
            "connection",
            "docker",
            "container",
            "host",
            "kernel",
            "oom",
        ],
        "metrics": ["cpu_used_percent", "ram_used_percent", "disk_used_percent", "load_1m"],
        "sub_types": {
            "cpu": "cpu_saturation",
            "memory": "memory_pressure",
            "disk": "disk_pressure",
            "network": "network_issue",
        },
    },
    {
        "class": "application",
        "keywords": [
            "error",
            "exception",
            "5xx",
            "4xx",
            "crash",
            "panic",
            "traceback",
            "stack overflow",
            "null pointer",
            "deadlock",
        ],
        "metrics": ["error_rate", "latency_p99_ms", "request_count"],
        "sub_types": {
            "error": "error_spike",
            "latency": "latency_degradation",
            "crash": "application_crash",
        },
    },
    {
        "class": "business",
        "keywords": [
            "revenue",
            "conversion",
            "order",
            "payment",
            "checkout",
            "user",
            "session",
            "funnel",
        ],
        "metrics": ["affected_users", "revenue_impact", "conversion_rate"],
        "sub_types": {
            "user": "user_impact",
            "payment": "payment_failure",
            "order": "order_failure",
        },
    },
    {
        "class": "security",
        "keywords": [
            "auth",
            "unauthorized",
            "403",
            "401",
            "brute force",
            "attack",
            "injection",
            "xss",
            "cve",
        ],
        "metrics": ["auth_failure_rate", "blocked_requests"],
        "sub_types": {"auth": "auth_failure", "attack": "attack_detected"},
    },
]


def classify_signal(
    *,
    signal: dict[str, Any],
    min_confidence: float = 0.3,
) -> SignalClassification:
    """信号类别分类 — 区分基础设施/应用/业务/安全告警.

    Composition note: pure algorithm. Output feeds into synthesize_action_plan
    to select appropriate remediation playbook.

    Args:
        signal: 信号 dict, 含 "message"(str) 和/或 metric 键值
        min_confidence: 最低置信度阈值

    Returns:
        SignalClassification
    """
    message = str(signal.get("message", "")).lower()
    signal_keys = set(signal.keys())

    scores: dict[str, float] = {}
    sub_types: dict[str, str | None] = {}

    for rule in _CLASS_RULES:
        cls = rule["class"]
        score = 0.0
        detected_sub: str | None = None

        # Keyword match
        for kw in rule["keywords"]:
            if kw in message:
                score += 0.3
                # Try to assign sub_type from keyword
                for sub_kw, sub_name in rule["sub_types"].items():
                    if sub_kw in kw:
                        detected_sub = sub_name
                        break

        # Metric key presence
        for metric_key in rule["metrics"]:
            if metric_key in signal_keys and signal.get(metric_key):
                score += 0.25

        scores[cls] = min(score, 1.0)
        sub_types[cls] = detected_sub

    best_class = max(scores, key=lambda c: scores[c]) if scores else "unknown"
    best_score = scores.get(best_class, 0.0)

    if best_score < min_confidence:
        return SignalClassification(
            signal_class="unknown",
            confidence=0.0,
            sub_type=None,
            reasoning="No class met minimum confidence threshold",
        )

    return SignalClassification(
        signal_class=best_class,  # type: ignore[arg-type]
        confidence=round(best_score, 3),
        sub_type=sub_types.get(best_class),
        reasoning=f"Matched {best_class} rules with score {round(best_score, 3)}",
    )
