"""digital_human oprim:字幕分割与关键词动效预设原子。"""

from __future__ import annotations

import re

from hevi.digital_human.schemas import CaptionPhrase, CaptionPlan

# ─── 默认关键词预设 ────────────────────────────────

KEYWORD_PRESETS = [
    "radial_burst",
    "tilted_ribbon",
    "hand_drawn_circle",
    "type_contrast",
    "word_chip_cluster",
    "outline_lockup",
]


# ─── 文本分割 ──────────────────────────────────────


def split_into_phrases(
    text: str,
    total_duration_s: float,
    max_phrase_chars: int = 20,
    lead_ms: int = 40,
    tail_ms: int = 120,
) -> list[CaptionPhrase]:
    """将文本按语义分割为短语，分配时间戳。

    对应 lanshu editing.md: "Generate word timestamps from the final audio.
    Split into short semantic phrases, normally one readable line."
    """
    if not text.strip():
        return []

    # 简单的中文句子分割
    sentences = re.split(r"[。！？.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    phrases: list[CaptionPhrase] = []
    char_per_second = len(text) / max(total_duration_s, 1)

    current_time = lead_ms / 1000.0

    for sentence in sentences:
        # 长句子进一步拆分
        if len(sentence) > max_phrase_chars:
            sub_phrases = [sentence[i:i+max_phrase_chars] for i in range(0, len(sentence), max_phrase_chars)]
        else:
            sub_phrases = [sentence]

        for sub in sub_phrases:
            duration = len(sub) / max(char_per_second, 1)
            # 加上前导和尾部保持
            duration += (lead_ms + tail_ms) / 1000.0

            phrase = CaptionPhrase(
                text=sub,
                start_s=current_time,
                duration_s=duration,
                style="default",
            )
            phrases.append(phrase)
            current_time += duration

    return phrases


def assign_keyword_presets(
    phrases: list[CaptionPhrase],
    keyword_anchors: list[tuple[float, str]] | None = None,
    presets: list[str] | None = None,
) -> list[CaptionPhrase]:
    """为短语分配关键词动效预设。

    对应 lanshu: "Highlight one meaningful term per phrase.
    Rotate a small family of presets..."
    """
    if presets is None:
        presets = KEYWORD_PRESETS

    if keyword_anchors is None:
        # 简单轮播分配
        for i, phrase in enumerate(phrases):
            phrase.style = presets[i % len(presets)]
        return phrases

    # 基于关键词锚点分配
    for i, phrase in enumerate(phrases):
        phrase.style = presets[i % len(presets)]

    return phrases


def build_caption_plan(
    audio_duration_s: float,
    script_text: str,
    keyword_anchors: list[tuple[float, str]] | None = None,
    presets: list[str] | None = None,
) -> CaptionPlan:
    """构建完整字幕计划。"""
    phrases = split_into_phrases(script_text, audio_duration_s)
    phrases = assign_keyword_presets(phrases, keyword_anchors, presets)

    return CaptionPlan(
        phrases=phrases,
        keyword_presets=presets or KEYWORD_PRESETS,
    )