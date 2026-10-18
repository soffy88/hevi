import hashlib
import re
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel


class LogCluster(BaseModel):
    cluster_id: str
    representative_message: str
    pattern: str  # 提取的 message template
    count: int
    first_seen_utc: str
    last_seen_utc: str
    example_messages: list[str]  # 前 5 条原始消息


class LogAnomalyClusters(BaseModel):
    clusters: list[LogCluster]
    anomaly_score: float  # 0-1, 异常程度
    total_lines: int
    unique_patterns: int


def _extract_pattern_naive(message: str) -> str:
    """Naive pattern extraction: replace numbers, hex, UUIDs, IPs."""
    p = message
    # Replace UUIDs
    p = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>", p
    )
    # Replace IPs
    p = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>", p)
    # Replace Hex
    p = re.sub(r"0x[0-9a-fA-F]+", "<HEX>", p)
    # Replace Numbers
    p = re.sub(r"\d+", "<NUM>", p)
    return p


def structured_log_anomaly_cluster(
    *,
    log_lines: list[dict[str, Any]],  # structlog_parse 输出后的 dict 列表
    time_window_sec: int | None = None,  # None=全部
    min_cluster_size: int = 2,
    pattern_extractor: Literal["drain", "naive"] = "naive",
) -> LogAnomalyClusters:
    """日志聚类 (按 message template)."""
    if not log_lines:
        return LogAnomalyClusters(clusters=[], anomaly_score=0.0, total_lines=0, unique_patterns=0)

    # Filter by time window if requested
    now = datetime.now(UTC)
    filtered_lines = []
    for line in log_lines:
        if time_window_sec is not None:
            ts_str = cast(str | None, line.get("timestamp"))
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if (now - ts).total_seconds() > time_window_sec:
                        continue
                except (ValueError, TypeError):
                    pass
        filtered_lines.append(line)

    clusters_data: dict[str, dict[str, Any]] = {}

    for line in filtered_lines:
        message_val = line.get("event") or line.get("msg") or line.get("message") or ""
        message = str(message_val)
        if not message:
            continue

        pattern = _extract_pattern_naive(message)
        pattern_hash = hashlib.sha256(pattern.encode("utf-8")).hexdigest()[:12]

        timestamp = cast(str, line.get("timestamp") or now.isoformat())

        if pattern_hash not in clusters_data:
            clusters_data[pattern_hash] = {
                "pattern": pattern,
                "representative": message,
                "count": 0,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "examples": [],
            }

        data = clusters_data[pattern_hash]
        data["count"] += 1
        data["last_seen"] = timestamp
        if len(data["examples"]) < 5:
            data["examples"].append(message)

    final_clusters = []
    for cluster_id, data in clusters_data.items():
        if data["count"] >= min_cluster_size:
            final_clusters.append(
                LogCluster(
                    cluster_id=cluster_id,
                    representative_message=cast(str, data["representative"]),
                    pattern=cast(str, data["pattern"]),
                    count=cast(int, data["count"]),
                    first_seen_utc=cast(str, data["first_seen"]),
                    last_seen_utc=cast(str, data["last_seen"]),
                    example_messages=cast(list[str], data["examples"]),
                )
            )

    total_lines = len(filtered_lines)
    unique_patterns = len(clusters_data)

    # Anomaly score: higher ratio of unique patterns / total lines might indicate anomalies
    anomaly_score = unique_patterns / total_lines if total_lines > 0 else 0.0

    return LogAnomalyClusters(
        clusters=final_clusters,
        anomaly_score=min(1.0, anomaly_score),
        total_lines=total_lines,
        unique_patterns=unique_patterns,
    )
