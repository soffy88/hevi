"""diagnose_pattern_match — 信号特征模式匹配诊断."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PatternMatchResult(BaseModel):
    matched: bool
    pattern_name: str | None
    confidence: float
    matched_features: list[str]
    detail: dict[str, Any]


_BUILTIN_PATTERNS: list[dict[str, Any]] = [
    {
        "name": "memory_pressure",
        "keywords": ["oom", "out of memory", "memory", "ram"],
        "threshold_key": "ram_used_percent",
        "threshold_op": "gt",
        "threshold_val": 85.0,
        "confidence": 0.9,
    },
    {
        "name": "cpu_saturation",
        "keywords": ["cpu", "throttle", "load average"],
        "threshold_key": "cpu_used_percent",
        "threshold_op": "gt",
        "threshold_val": 90.0,
        "confidence": 0.9,
    },
    {
        "name": "queue_backlog",
        "keywords": ["queue", "backlog", "unacked", "lag"],
        "threshold_key": "queue_depth",
        "threshold_op": "gt",
        "threshold_val": 1000,
        "confidence": 0.85,
    },
    {
        "name": "connection_exhaustion",
        "keywords": ["connection", "pool", "exhausted", "too many clients"],
        "threshold_key": "active_connections",
        "threshold_op": "gt",
        "threshold_val": 95,
        "confidence": 0.85,
    },
    {
        "name": "disk_pressure",
        "keywords": ["disk", "inode", "storage", "no space"],
        "threshold_key": "disk_used_percent",
        "threshold_op": "gt",
        "threshold_val": 85.0,
        "confidence": 0.9,
    },
]


def diagnose_pattern_match(
    *,
    signal: dict[str, Any],
    patterns: list[dict[str, Any]] | None = None,
    min_confidence: float = 0.5,
) -> PatternMatchResult:
    """信号特征模式匹配 — 将告警/指标信号映射到已知故障模式.

    Composition note: pure algorithm, no LLM or external I/O.
    Designed to be composed with compute_severity_score for full triage pipeline.

    Args:
        signal: 信号 dict — 应包含 "message"(str) 和/或 metric 键值对
                e.g. {"message": "OOM killed", "ram_used_percent": 92.0}
        patterns: 自定义模式列表; None 时使用内置模式
                  每条模式: {name, keywords, threshold_key, threshold_op, threshold_val, confidence}
        min_confidence: 最低置信度阈值

    Returns:
        PatternMatchResult
    """
    pattern_list = patterns if patterns is not None else _BUILTIN_PATTERNS
    message = str(signal.get("message", "")).lower()

    best: PatternMatchResult | None = None
    best_score = 0.0

    for pat in pattern_list:
        matched_features: list[str] = []
        score = 0.0
        base_conf = float(pat.get("confidence", 0.7))

        # Keyword match on message
        for kw in pat.get("keywords", []):
            if kw.lower() in message:
                matched_features.append(f"keyword:{kw}")
                score += 0.5

        # Threshold check on numeric signal field
        tkey = pat.get("threshold_key")
        if tkey and tkey in signal:
            val = float(signal[tkey])
            thresh = float(pat.get("threshold_val", 0))
            op = pat.get("threshold_op", "gt")
            if (
                (op == "gt" and val > thresh)
                or (op == "lt" and val < thresh)
                or (op == "eq" and val == thresh)
            ):
                matched_features.append(f"threshold:{tkey}{op}{thresh}")
                score += 0.5

        if score > 0:
            confidence = round(min(base_conf * min(score, 1.0) * 2, 1.0), 3)
            if confidence >= min_confidence and confidence > best_score:
                best_score = confidence
                best = PatternMatchResult(
                    matched=True,
                    pattern_name=pat["name"],
                    confidence=confidence,
                    matched_features=matched_features,
                    detail={"pattern": pat["name"], "signal_keys": list(signal.keys())},
                )

    if best:
        return best

    return PatternMatchResult(
        matched=False,
        pattern_name=None,
        confidence=0.0,
        matched_features=[],
        detail={"reason": "no pattern matched", "signal_keys": list(signal.keys())},
    )
