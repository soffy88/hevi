"""字幕句边界与时钟分配:合句、补句号、按字重切时长。

对齐 Voice-Pro `abus_nlp_spacy.merge_and_split_events`,不依赖 spaCy。
3O 归属(待上游): `oprim.cue_clock`。
"""

from __future__ import annotations

import re

from hevi.voicepro.schemas import TimedCue

MAX_MERGE_GAP_S = 1.0
MIN_DURATION_S = 1.0
SENTENCE_ENDINGS = frozenset(".!?。！？…")
NON_SPACING_LANGS = frozenset({"ja", "zh", "th", "km", "lo", "yue"})
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？…])\s+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_PUNCT_MAP = str.maketrans(
    {
        "．": ".",
        "！": "!",
        "？": "?",
        "，": ",",
        "：": ":",
        "；": ";",
        "　": " ",
    }
)
_QUESTION_START = re.compile(
    r"^(who|what|when|where|why|how|谁|什么|何时|哪里|为何|怎么)",
    re.IGNORECASE,
)


def detect_lang_hint(text: str) -> str:
    if _CJK.search(text or ""):
        return "zh"
    return "en"


def normalize_text(text: str, lang: str = "") -> str:
    del lang
    cleaned = (text or "").translate(_PUNCT_MAP)
    return re.sub(r"\s+", " ", cleaned).strip()


def split_into_sentences(text: str) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) < 10 and not _SENT_SPLIT.search(cleaned):
        return [cleaned]
    parts = [part.strip() for part in _SENT_SPLIT.split(cleaned) if part.strip()]
    return parts or [cleaned]


def is_complete_sentence(text: str) -> bool:
    if not text or len(text) < 3:
        return False
    return text[-1] in SENTENCE_ENDINGS or len(text) > 20


def complete_sentence(text: str) -> str:
    stripped = (text or "").rstrip()
    if not stripped:
        return stripped
    if stripped[-1] in SENTENCE_ENDINGS:
        return stripped
    return stripped + ("?" if _QUESTION_START.search(stripped) else ".")


def should_break_group(
    prev_end_s: float,
    next_start_s: float,
    *,
    max_gap_s: float = MAX_MERGE_GAP_S,
) -> bool:
    return next_start_s - prev_end_s > max_gap_s


def join_group_text(texts: list[str], lang: str = "") -> str:
    cleaned = [normalize_text(item, lang) for item in texts if normalize_text(item, lang)]
    if lang in NON_SPACING_LANGS:
        return "".join(cleaned)
    return " ".join(cleaned)


def char_weighted_spans(
    texts: list[str],
    start_s: float,
    end_s: float,
    *,
    min_duration_s: float = MIN_DURATION_S,
) -> list[tuple[float, float]]:
    """按字符占比把 [start,end] 切成与 texts 对齐的区间;每段至少 min_duration_s。"""
    if not texts:
        return []
    total_chars = sum(max(len(text), 1) for text in texts)
    span = max(end_s - start_s, min_duration_s * len(texts))
    cursor = start_s
    last = start_s + span
    spans: list[tuple[float, float]] = []
    for index, text in enumerate(texts):
        duration = max(min_duration_s, span * max(len(text), 1) / total_chars)
        sent_start = start_s if index == 0 else cursor
        sent_end = sent_start + duration
        sent_end = last if index == len(texts) - 1 else min(sent_end, last)
        if sent_end - sent_start < min_duration_s and last - sent_start >= min_duration_s:
            sent_end = sent_start + min_duration_s
        if sent_end > last:
            sent_start = max(start_s, last - min_duration_s)
            sent_end = last
        spans.append((sent_start, sent_end))
        cursor = sent_end
    return spans


def merge_sentence_fragments(sentences: list[str]) -> list[str]:
    merged: list[str] = []
    current = ""
    for sent in sentences:
        if current and not is_complete_sentence(current):
            current = f"{current} {sent}".strip()
        else:
            if current:
                merged.append(current)
            current = sent
    if current:
        merged.append(current)
    return [complete_sentence(item) if not is_complete_sentence(item) else item for item in merged]


def group_cues(cues: list[TimedCue], *, max_gap_s: float = MAX_MERGE_GAP_S) -> list[list[TimedCue]]:
    groups: list[list[TimedCue]] = []
    current: list[TimedCue] = []
    for cue in cues:
        if not (cue.text or "").strip():
            continue
        if current and should_break_group(current[-1].end, cue.start, max_gap_s=max_gap_s):
            groups.append(current)
            current = []
        current.append(cue)
    if current:
        groups.append(current)
    return groups
