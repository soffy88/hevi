"""字幕润色 —— 对照 xiaohu-subtitle-polish。

纠 ASR 专有名词、按语义断句、去尾标点、术语保留。LLM 可选;无模型时 glossary
+ 规则仍可跑,不假装已翻译。
"""

from __future__ import annotations

import re

from hevi.ingest.video_transcript import TranscriptSegment

# 常见 ASR 听错(英文专有名词);调用方可再叠加 glossary。
DEFAULT_GLOSSARY: dict[str, str] = {
    "cloud code": "Claude Code",
    "ncp": "MCP",
    "emcp": "MCP",
    "gpt 4": "GPT-4",
    "gpt-4o": "GPT-4o",
}


_TRAIL_PUNCT = re.compile(r"[。．.、,，;；:：]+$")


def apply_glossary(text: str, glossary: dict[str, str] | None = None) -> str:
    """按长短优先替换术语,大小写不敏感。"""
    merged = dict(DEFAULT_GLOSSARY)
    if glossary:
        merged.update({str(k): str(v) for k, v in glossary.items() if k})
    out = text
    for src, dst in sorted(merged.items(), key=lambda kv: len(kv[0]), reverse=True):
        if not src:
            continue
        out = re.sub(re.escape(src), dst, out, flags=re.IGNORECASE)
    return out


def strip_trailing_punct(text: str) -> str:
    """字幕行尾标点去掉,画面更干净。"""
    return _TRAIL_PUNCT.sub("", (text or "").strip())


def polish_segment(
    seg: TranscriptSegment,
    *,
    glossary: dict[str, str] | None = None,
) -> TranscriptSegment:
    text = strip_trailing_punct(apply_glossary(seg.text, glossary))
    return TranscriptSegment(
        start=seg.start,
        end=seg.end,
        text=text or seg.text,
        speaker=seg.speaker,
        words=seg.words,
    )


def polish_segments(
    segments: list[TranscriptSegment],
    *,
    glossary: dict[str, str] | None = None,
) -> list[TranscriptSegment]:
    return [polish_segment(seg, glossary=glossary) for seg in segments]


def pair_bilingual(
    source: list[TranscriptSegment],
    translated: list[TranscriptSegment],
) -> list[tuple[TranscriptSegment, TranscriptSegment]]:
    """按索引对齐原文/译文。缺译文时用原文占位(调用方应标未译)。"""
    pairs: list[tuple[TranscriptSegment, TranscriptSegment]] = []
    for i, src in enumerate(source):
        tgt = translated[i] if i < len(translated) else src
        pairs.append((src, tgt))
    return pairs
