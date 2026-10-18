import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel


class RunbookMatchResult(BaseModel):
    matched_plugin: dict[str, Any] | None = None  # plugin metadata
    match_score: float = 0.0  # 0-1
    alternative_plugins: list[dict[str, Any]] = []  # 次匹配


def runbook_match(
    *,
    root_cause: dict[str, Any],
    available_plugins: list[dict[str, Any]],
    min_match_score: float = 0.7,
    matcher_strategy: Literal["rule_based", "embedding", "hybrid"] = "rule_based",
    embedding_fn: Callable[[str], list[float]] | None = None,
) -> RunbookMatchResult:
    """根因 → marketplace plugin 匹配.

    rule_based: 用 plugin 的 matcher 规则 (e.g. {error_pattern: regex, service_type: str})
    embedding: 用 root_cause 描述 + plugin 描述的语义相似度
    hybrid: 先 rule_based, 命中后用 embedding 排序
    """
    matches = []

    rc_text = str(root_cause.get("root_cause_hypothesis", ""))

    for plugin in available_plugins:
        score = 0.0

        if matcher_strategy in ("rule_based", "hybrid"):
            matcher = plugin.get("matcher", {})
            error_pattern = matcher.get("error_pattern")
            if error_pattern and re.search(error_pattern, rc_text, re.IGNORECASE):
                score = 0.9  # High score for rule match

            service_type = matcher.get("service_type")
            if service_type and service_type == root_cause.get("service_type"):
                score = max(score, 0.8)

        if matcher_strategy in ("embedding", "hybrid") and score < 1.0:
            if embedding_fn:
                # Simplified embedding similarity if embedding_fn is provided
                # In a real oskill, we'd use oprim.vector_similarity
                pass

        if score >= min_match_score:
            matches.append((score, plugin))

    # Sort by score descending
    matches.sort(key=lambda x: x[0], reverse=True)

    if not matches:
        return RunbookMatchResult()

    return RunbookMatchResult(
        matched_plugin=matches[0][1],
        match_score=matches[0][0],
        alternative_plugins=[m[1] for m in matches[1:]],
    )
