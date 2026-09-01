"""旁白驱动的语义时序契约(cs-board semantic-timing-contract v2 的 Hevi 内化)。

硬纪律:
1. 先有旁白,再有短语时间表,再规划画面。禁止按时长/字数均分估算毫秒。
2. 每条 Cue 必须引用已经存在的 phrase id,不得手写 start_ms。
3. 对齐覆盖率不达标 → 失败,不允许退回「按字数估」。
4. relationship_type 默认 none;只有原文出现步骤/因果词才允许箭头。
"""

from __future__ import annotations

import re
from typing import Any

GLOBAL_SOURCE_COVERAGE_MIN = 0.72
ANCHOR_COVERAGE_MIN = 0.65
ANCHOR_CONFIDENCE_MIN = 0.20

_DIGIT_SPOKEN = str.maketrans("0123456789", "零一二三四五六七八九")
_SEQUENCE_HINT = re.compile(r"首先|然后|接着|最后|第一步|第二步|第[一二三四五六七八九十0-9]+步")
_CAUSE_HINT = re.compile(r"因为|所以|导致|因此|以致")


def phrases_from_narration(copy: str) -> list[str]:
    """旁白切短语。书名号整段保留,不以字数估时。"""
    phrases: list[str] = []
    for piece in re.split(r"(《[^》]+》)", copy or ""):
        if not piece:
            continue
        if piece.startswith("《") and piece.endswith("》"):
            phrases.append(piece)
            continue
        phrases.extend(
            value.strip()
            for value in re.findall(r"[^，,。！？!?；;：:\n]+[，,。！？!?；;：:]?", piece)
            if value.strip()
        )
    return [value for value in phrases if _normalized(value)]


def _normalized(text: str) -> str:
    lowered = str(text).translate(_DIGIT_SPOKEN).lower()
    return "".join(ch for ch in lowered if ch.isalnum())


def _caption_stream(captions: list[dict[str, Any]]) -> tuple[str, list[int], list[dict[str, Any]]]:
    if not captions:
        raise RuntimeError("语音对齐结果不包含 token 时间戳")
    normalized_text: list[str] = []
    character_tokens: list[int] = []
    cleaned: list[dict[str, Any]] = []
    for raw in captions:
        if not isinstance(raw, dict):
            continue
        token_text = _normalized(str(raw.get("text") or ""))
        if not token_text:
            continue
        start_ms = round(float(raw.get("startMs") or raw.get("start_ms") or 0))
        end_ms = round(float(raw.get("endMs") or raw.get("end_ms") or start_ms))
        if end_ms < start_ms:
            continue
        confidence = float(raw.get("confidence", 1.0) or 0.0)
        token_index = len(cleaned)
        cleaned.append(
            {
                "text": token_text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "confidence": confidence,
            }
        )
        normalized_text.extend(token_text)
        character_tokens.extend([token_index] * len(token_text))
    if not cleaned:
        raise RuntimeError("语音对齐结果没有可用的中文或字母数字 token")
    return "".join(normalized_text), character_tokens, cleaned


def _span_for(haystack: str, needle: str, cursor: int) -> tuple[int, int] | None:
    if not needle:
        return None
    at = haystack.find(needle, cursor)
    if at < 0:
        at = haystack.find(needle)
    if at < 0:
        return None
    return at, at + len(needle)


def build_phrase_timeline(
    narration: str,
    captions: list[dict[str, Any]],
    *,
    coverage_min: float = GLOBAL_SOURCE_COVERAGE_MIN,
) -> dict[str, Any]:
    """把旁白切成短语,只用 caption 的真实起止毫秒。失败即抛,不估时。"""
    stream, token_at, tokens = _caption_stream(captions)
    phrases = phrases_from_narration(narration)
    if not phrases:
        raise RuntimeError("旁白切不出短语")
    rows: list[dict[str, Any]] = []
    cursor = 0
    matched_chars = 0
    for index, phrase in enumerate(phrases, start=1):
        needle = _normalized(phrase)
        span = _span_for(stream, needle, cursor)
        if span is None:
            raise RuntimeError(f"短语无法对齐到语音 token: {phrase[:24]}")
        start_i, end_i = span
        token_slice = token_at[start_i:end_i]
        if not token_slice:
            raise RuntimeError(f"短语没有对应的语音边界: {phrase[:24]}")
        first, last = tokens[token_slice[0]], tokens[token_slice[-1]]
        coverage = len(needle) / max(len(_normalized(phrase)), 1)
        confidence = min(first["confidence"], last["confidence"])
        if coverage < ANCHOR_COVERAGE_MIN or confidence < ANCHOR_CONFIDENCE_MIN:
            raise RuntimeError(
                f"短语对齐覆盖率/置信度不足: {phrase[:24]} coverage={coverage:.2f}"
            )
        rows.append(
            {
                "id": f"p{index:02d}",
                "text": phrase,
                "start_ms": int(first["start_ms"]),
                "end_ms": int(last["end_ms"]),
                "coverage": coverage,
                "confidence": confidence,
                "boundary_source": "caption-token",
            }
        )
        matched_chars += len(needle)
        cursor = end_i
    source_coverage = matched_chars / max(len(stream), 1)
    if source_coverage < coverage_min:
        raise RuntimeError(
            f"全文对齐覆盖率 {source_coverage:.2f} < {coverage_min:.2f},禁止按时长估算"
        )
    return {
        "narration": narration,
        "coverage": source_coverage,
        "phrases": rows,
    }


def infer_relationship(page_text: str) -> str:
    """关系默认 none。只有原文有步骤/因果证据才允许箭头。"""
    text = page_text or ""
    if _SEQUENCE_HINT.search(text):
        return "sequence"
    if _CAUSE_HINT.search(text):
        return "cause"
    return "none"


def page_from_phrases(
    phrases: list[dict[str, Any]],
    *,
    title: str,
    idea: str,
    trigger_ids: list[str],
    source_text: str = "",
) -> dict[str, Any]:
    known = {str(row["id"]) for row in phrases}
    missing = [pid for pid in trigger_ids if pid not in known]
    if missing:
        raise RuntimeError(f"页面引用了不存在的短语编号: {missing}")
    by_id = {str(row["id"]): row for row in phrases}
    keywords = [{"label": by_id[pid]["text"], "trigger_phrase_id": pid} for pid in trigger_ids]
    return {
        "page_title": title,
        "core_idea": idea,
        "relationship_type": infer_relationship(source_text or idea),
        "keywords": keywords,
        "start_ms": int(by_id[trigger_ids[0]]["start_ms"]) if trigger_ids else 0,
        "end_ms": int(by_id[trigger_ids[-1]]["end_ms"]) if trigger_ids else 0,
    }
