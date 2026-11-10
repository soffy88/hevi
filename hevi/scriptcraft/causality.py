"""Causality check: adjacent beats must be joined by 但是 or 所以, not 然后."""

from __future__ import annotations

from typing import Any

CAUSAL = ("但是", "但", "却", "所以", "因此", "因为", "结果", "于是", "反而", "然而",
          "直到", "没想到", "偏偏", "正因", "这才", "因此才", "可")
SEQUENCE = ("然后", "接着", "后来", "之后", "再", "又", "随后", "紧接着", "跟着")
REVERSAL_HINTS = ("却", "反而", "没想到", "揭开", "发现", "真相", "背叛", "翻脸", "反悔", "拒绝")


def _event_text(event: dict[str, Any] | str) -> str:
    if isinstance(event, str):
        return event
    for key in ("event", "text", "core_event", "summary", "action"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def connector_of(event: dict[str, Any] | str) -> str:
    if isinstance(event, dict):
        explicit = str(event.get("connector") or "").strip()
        if explicit:
            return explicit
    text = _event_text(event)
    for word in (*CAUSAL, *SEQUENCE):
        if text.startswith(word):
            return word
    return ""


def is_causal(connector: str, text: str = "") -> bool:
    return connector in CAUSAL or any(word in text for word in CAUSAL)


def suggest_connector(previous: dict[str, Any] | str, current: dict[str, Any] | str) -> str:
    current_text = _event_text(current)
    if any(word in current_text for word in REVERSAL_HINTS):
        return "但是"
    if any(word in current_text for word in ("拿到", "签下", "曝光", "抓住", "赢了", "成功", "揭穿")):
        return "所以"
    return "所以"


def check_causality(events: list[dict[str, Any] | str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    pairs = 0
    causal_pairs = 0
    sequence_pairs = 0
    chain = 0
    longest_sequence_chain = 0
    for index in range(1, len(events)):
        pairs += 1
        previous = events[index - 1]
        current = events[index]
        connector = connector_of(current)
        text = _event_text(current)
        if is_causal(connector, text):
            causal_pairs += 1
            chain = 0
            continue
        sequence_pairs += 1
        chain += 1
        longest_sequence_chain = max(longest_sequence_chain, chain)
        severity = "must" if chain >= 3 or connector in {"然后", "接着", "后来"} else "should"
        suggestion = suggest_connector(previous, current)
        findings.append({
            "rule": "X-THEN",
            "severity": severity,
            "message": f"第 {index}→{index + 1} 个事件只靠「{connector or '顺序'}」连接；改成「{suggestion}」",
            "ref": f"event[{index + 1}]",
            "suggestion": suggestion,
            "current": text,
            "previous": _event_text(previous),
        })
    ratio = (causal_pairs / pairs) if pairs else 1.0
    if pairs and ratio < 0.7:
        findings.append({
            "rule": "X-RATIO",
            "severity": "must",
            "message": f"因果连接只占 {ratio:.0%}（需 ≥70%），大纲读起来像流水账",
            "ref": "outline",
            "suggestion": "把相邻事件逐个问：这件事是上一件的「但是」还是「所以」？",
        })
    return {
        "passed": not any(f["severity"] == "must" for f in findings),
        "pairs": pairs,
        "causal_pairs": causal_pairs,
        "sequence_pairs": sequence_pairs,
        "causal_ratio": round(ratio, 3),
        "longest_sequence_chain": longest_sequence_chain,
        "findings": findings,
    }


def rewrite_chain(events: list[dict[str, Any] | str]) -> list[dict[str, Any]]:
    """Return events with a suggested connector added where one is missing."""
    out: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        item = dict(event) if isinstance(event, dict) else {"event": str(event)}
        if index and not connector_of(item):
            item["connector"] = suggest_connector(events[index - 1], item)
        out.append(item)
    return out


__all__ = [
    "CAUSAL",
    "SEQUENCE",
    "check_causality",
    "connector_of",
    "is_causal",
    "rewrite_chain",
    "suggest_connector",
]
