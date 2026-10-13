"""5-segment heartbeat narrative structure planner (oskill, pure function).

Implements the "High-Completion 5-Stage Heartbeat Engine" from the
vendored stickman-video-director contract:

  Stage 1  黄金钩子 Golden Hook
  Stage 2  打破常识 Disrupting Assumptions
  Stage 3  拉出内幕 Unveiling Insider Secrets
  Stage 4  真相揭秘 Ultimate Truth Revelation
  Stage 5  升华互动 Elevation & High-Engagement Discussion

The structure is **optional** — it never changes the default comic script
planner.  Callers pass ``structure="heartbeat5"`` to opt in.

Core rules:
- N clips, N = duration_s / 10 (each clip ~10s).
- The hook (Stage 1) must land inside the first 2–5 s window.
- Facts are preserved: no invented numbers, names, or quotations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "HeartbeatSegment",
    "HeartbeatPlan",
    "clip_count_for_duration",
    "hook_window_s",
    "plan_heartbeat5",
]

#: Clip length in seconds (one "heartbeat" row).
CLIP_S = 10.0

#: Hook must land inside [HOOK_MIN_S, HOOK_MAX_S] of Clip 1.
HOOK_MIN_S = 2.0
HOOK_MAX_S = 5.0

# Stage display labels (zh + en), one per heartbeat stage.
STAGES: list[tuple[str, str]] = [
    ("黄金钩子", "Golden Hook"),
    ("打破常识", "Disrupting Assumptions"),
    ("拉出内幕", "Unveiling Insider Secrets"),
    ("真相揭秘", "Ultimate Truth Revelation"),
    ("升华互动", "Elevation & High-Engagement Discussion"),
]


def clip_count_for_duration(duration_s: float) -> int:
    """Number of ~10s clips for a duration (N = duration / 10, min 1)."""
    n = max(1, round(duration_s / CLIP_S))
    return n


def hook_window_s(duration_s: float) -> tuple[float, float]:
    """Window in which the hook must land for the given duration.

    Short videos (<=60s): first 2–5 s, i.e. inside beat [0–3s] of Clip 1.
    Longer videos (3–5 min): premise across first 5–15 s.
    """
    if duration_s <= 60.0:
        return (HOOK_MIN_S, HOOK_MAX_S)
    return (5.0, 15.0)


@dataclass
class HeartbeatSegment:
    """One ~10s clip row of the heartbeat storyboard."""

    clip_index: int          # 0-based
    stage_index: int         # 0..4 (five stages)
    stage_zh: str
    stage_en: str
    narration: str           # fact-preserving narration for the clip
    visual_desc: str         # visual description
    beats: dict[str, str] = field(default_factory=dict)
    # beats: {"0-3s": "...", "3-7s": "...", "7-10s": "..."}
    duration_s: float = CLIP_S
    hook: bool = False       # True only for the Stage-1 hook clip

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_index": self.clip_index,
            "stage_index": self.stage_index,
            "stage_zh": self.stage_zh,
            "stage_en": self.stage_en,
            "narration": self.narration,
            "visual_desc": self.visual_desc,
            "beats": dict(self.beats),
            "duration_s": self.duration_s,
            "hook": self.hook,
        }


@dataclass
class HeartbeatPlan:
    """Complete heartbeat5 plan for a source text + duration."""

    title: str
    topic: str
    duration_s: float
    clip_count: int
    hook_window: tuple[float, float]
    narration_lang: str
    segments: list[HeartbeatSegment] = field(default_factory=list)
    source_facts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "topic": self.topic,
            "duration_s": self.duration_s,
            "clip_count": self.clip_count,
            "hook_window": list(self.hook_window),
            "narration_lang": self.narration_lang,
            "segments": [s.to_dict() for s in self.segments],
            "source_facts": list(self.source_facts),
        }


def _split_sentences(text: str) -> list[str]:
    """Split Chinese/English text into sentences (no truncation)."""
    if not text:
        return []
    raw = str(text).strip()
    if not raw:
        return []
    # Match word-like tokens followed by any terminal punctuation (CJK or Latin)
    pattern = r"[\w\s]+(?:[。！？…!?.]+|$)"
    parts = [m.group(0).strip() for m in re.finditer(pattern, raw) if m.group(0).strip()]
    return parts


def _distribute_sentences(
    sentences: list[str],
    clip_count: int,
) -> list[list[str]]:
    """Distribute sentences across N clips, preserving order.

    Stage 1 (hook) always gets the first sentence. Remaining sentences
    are spread over the remaining stages proportionally.
    """
    if clip_count <= 0:
        return []
    buckets: list[list[str]] = [[] for _ in range(clip_count)]
    if not sentences:
        return buckets
    # Hook (clip 0) gets sentence 0; remaining spread round-robin
    buckets[0].append(sentences[0])
    rest = sentences[1:]
    if clip_count == 1:
        buckets[0].extend(rest)
        return buckets
    for i, sent in enumerate(rest):
        idx = 1 + (i % (clip_count - 1))
        buckets[idx].append(sent)
    return buckets


def _stage_for_clip(clip_index: int, clip_count: int) -> int:
    """Map clip index -> stage index (0..4).

    Hook (stage 0) always on clip 0; stage 4 (elevation) always on
    last clip; middle stages distributed across the remaining clips.
    """
    if clip_count <= 1:
        return 0
    if clip_index == 0:
        return 0
    if clip_index == clip_count - 1:
        return 4
    # middle clips: distribute stages 1..3 across indices 1..clip_count-2
    middle = clip_count - 2
    stage_span = 3  # stages 1,2,3
    if middle <= 0:
        return 1
    # map clip_index in [1, clip_count-2] to stage in [1,3]
    ratio = (clip_index - 1) / max(1, middle)
    return 1 + min(stage_span - 1, int(ratio * stage_span))


def _extract_facts(text: str) -> list[str]:
    """Best-effort factual tokens present in source (numbers, names).

    Used for the fact-preservation invariant: output narration may only
    contain facts that appear in the source.
    """
    facts: list[str] = []
    # numbers (incl. percentages, decimals)
    for m in re.finditer(r"\d+(?:\.\d+)?%?", text):
        tok = m.group(0)
        if tok not in facts:
            facts.append(tok)
    # capitalized English words (probable names)
    for m in re.finditer(r"\b[A-Z][a-z]+\b", text):
        tok = m.group(0)
        if tok not in facts:
            facts.append(tok)
    return facts


def _build_beats(narration: str, stage_idx: int) -> dict[str, str]:
    """Three timed beats per clip: [0-3s], [3-7s], [7-10s]."""
    sentences = _split_sentences(narration)
    if len(sentences) >= 3:
        return {
            "0-3s": sentences[0],
            "3-7s": sentences[1],
            "7-10s": sentences[2],
        }
    if len(sentences) == 2:
        return {"0-3s": sentences[0], "3-7s": sentences[1], "7-10s": sentences[1]}
    if len(sentences) == 1:
        return {"0-3s": sentences[0], "3-7s": sentences[0], "7-10s": sentences[0]}
    return {"0-3s": narration, "3-7s": narration, "7-10s": narration}


def plan_heartbeat5(
    *,
    source_text: str,
    duration_s: float,
    narration_lang: str = "zh",
    title: str | None = None,
    topic: str | None = None,
) -> HeartbeatPlan:
    """Plan a 5-stage heartbeat storyboard from a source text.

    Args:
        source_text: The source narration/article (Chinese or English).
        duration_s: Target duration in seconds (must be > 0).
        narration_lang: "zh" or "en".
        title: optional title override.
        topic: optional topic override.

    Returns:
        HeartbeatPlan with N = duration_s/10 segments.  Hook lands
        inside the 2–5s window (short videos) or 5–15s (long videos).

    Raises:
        ValueError: if duration_s <= 0.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")

    clip_count = clip_count_for_duration(duration_s)
    sentences = _split_sentences(source_text)
    if not sentences:
        sentences = [str(source_text).strip()]
    buckets = _distribute_sentences(sentences, clip_count)

    facts = _extract_facts(source_text)
    hw = hook_window_s(duration_s)

    segments: list[HeartbeatSegment] = []
    for i in range(clip_count):
        stage_idx = _stage_for_clip(i, clip_count)
        stage_zh, stage_en = STAGES[stage_idx]
        narr = "".join(buckets[i]).strip()
        if not narr and i == 0:
            narr = sentences[0] if sentences else ""
        seg = HeartbeatSegment(
            clip_index=i,
            stage_index=stage_idx,
            stage_zh=stage_zh,
            stage_en=stage_en,
            narration=narr,
            visual_desc=narr,
            beats=_build_beats(narr, stage_idx),
            duration_s=CLIP_S,
            hook=(i == 0),
        )
        segments.append(seg)

    return HeartbeatPlan(
        title=title or (topic or "heartbeat5")[:40],
        topic=topic or (title or ""),
        duration_s=duration_s,
        clip_count=clip_count,
        hook_window=hw,
        narration_lang=narration_lang,
        segments=segments,
        source_facts=facts,
    )
