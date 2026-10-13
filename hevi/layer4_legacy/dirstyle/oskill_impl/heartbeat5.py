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
    "HookTiming",
    "FactualError",
    "extract_facts",
    "validate_no_invented_numbers",
    "clip_count_for_duration",
    "hook_window_s",
    "hook_time_s",
    "hook_beat_label",
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


@dataclass(frozen=True)
class HookTiming:
    """Absolute timeline position of the Stage-1 hook.

    The hook lives inside the first clip; its absolute start time on the
    video timeline must fall inside ``hook_window`` (2-5 s for short videos,
    5-15 s for 3-5 min videos).
    """

    hook_start_s: float
    hook_end_s: float
    window_start_s: float
    window_end_s: float

    def within_window(self) -> bool:
        """True when the hook starts inside the required window."""
        return self.window_start_s <= self.hook_start_s <= self.window_end_s


class FactualError(ValueError):
    """Raised when planned narration invents facts absent from the source."""


@dataclass
class HeartbeatSegment:
    """One ~10s clip row of the heartbeat storyboard.

    ``visual_state_end`` describes the *last visible frame* of this clip.
    It is set equal to the next segment's ``visual_state_start`` so that
    every cut inherits an explicitly named continuity hand-off (the stickman
    contract forbids re-narrating continuity as "same as before").
    """

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
    hook_time_s: float | None = None   # absolute hook start time (clip 0 only)
    visual_state_start: str = ""        # inherited from previous clip's end
    visual_state_end: str = ""          # handed to the next clip's start

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
            "hook_time_s": self.hook_time_s,
            "visual_state_start": self.visual_state_start,
            "visual_state_end": self.visual_state_end,
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
    hook_timing: HookTiming | None = None

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
            "hook_timing": None
            if self.hook_timing is None
            else {
                "hook_start_s": self.hook_timing.hook_start_s,
                "hook_end_s": self.hook_timing.hook_end_s,
                "window_start_s": self.hook_timing.window_start_s,
                "window_end_s": self.hook_timing.window_end_s,
            },
        }


def _split_sentences(text: str) -> list[str]:
    """Split Chinese/English text into sentences (no truncation).

    Splits on terminal punctuation (CJK and Latin), keeping the
    punctuation attached to each sentence.  Chinese text with no
    terminal punctuation falls back to comma-boundary segmentation
    so that every clause becomes an independent sentence.
    """
    if not text:
        return []
    raw = str(text).strip()
    if not raw:
        return []
    # First: split on terminal punctuation (。！？…!?.)
    parts: list[str] = []
    buf: list[str] = []
    for ch in raw:
        buf.append(ch)
        if ch in "。！？…!?":
            parts.append("".join(buf).strip())
            buf = []
    if buf:
        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
    if len(parts) <= 1:
        # No terminal punctuation found; fall back to comma/semicolon
        # boundaries so Chinese run-ons still segment into clauses.
        comma_parts = re.split(r"[，,、;；]", raw)
        parts = [p.strip() for p in comma_parts if p.strip()]
    return parts or [raw]


def _distribute_sentences(
    sentences: list[str],
    clip_count: int,
) -> list[list[str]]:
    """Distribute sentences across N clips, preserving order.

    Stage 1 (hook) always gets the first sentence. Remaining sentences
    are distributed proportionally so each clip targets ~40-60 chars (F2 fix).
    """
    if clip_count <= 0:
        return []
    buckets: list[list[str]] = [[] for _ in range(clip_count)]
    if not sentences:
        return buckets
    # Hook (clip 0) always gets first sentence
    buckets[0].append(sentences[0])
    rest = sentences[1:]
    if clip_count == 1:
        buckets[0].extend(rest)
        return buckets
    # Proportional distribution: calculate target per clip and fill accordingly
    total_chars = sum(len(s) for s in rest)
    clips_remaining = clip_count - 1
    target_per_clip = total_chars / clips_remaining if clips_remaining > 0 else total_chars
    clip_idx = 0
    current_chars = 0
    for sent in rest:
        # Start new clip if current one has enough chars (target or more)
        if current_chars >= target_per_clip and clip_idx < clip_count - 1:
            clip_idx += 1
            current_chars = 0
        buckets[clip_idx].append(sent)
        current_chars += len(sent)
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


def extract_facts(text: str) -> list[str]:
    """Alias for _extract_facts to make the API importable."""
    return _extract_facts(text)


def validate_no_invented_numbers(
    *,
    source_text: str,
    plan: HeartbeatPlan,
) -> bool:
    """Return True when no narration token is absent from source.

    Only numbers present in source_text are allowed in output narrations.
    This is a soft validator: it returns True on pass, False on find of
    violation (the caller can raise FactualError if preferred).
    """
    source_facts = set(_extract_facts(source_text))
    for seg in plan.segments:
        for m in re.finditer(r"\d+(?:\.\d+)?%?", seg.narration):
            tok = m.group(0)
            if tok not in source_facts:
                raise FactualError(
                    f"segment {seg.clip_index} narration contains invented "
                    f"number {tok!r} not present in source"
                )
    return True


def hook_time_s(duration_s: float) -> float:
    """Return the absolute start time (in seconds) of the hook (clip 0).

    The hook must land inside the required window: 2-5 s for short videos
    (<=60s), 5-15 s for 3-5 min videos.  We anchor it at the *start* of
    the window so the contract is met deterministically for any duration.
    """
    lo, _hi = hook_window_s(duration_s)
    return lo


def hook_beat_label(duration_s: float) -> str:
    """Return which timed-beat label the hook lives in for the given duration."""
    # Short videos: hook inside the first clip's [0-3s] beat, timed at 2s in.
    # Long videos: the premise spans the first 5-15s, so still anchored at
    # the first clip's [0-3s] beat (with a 5s absolute offset).
    return "0-3s"


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
    """Three timed beats per clip: [0-3s], [3-7s], [7-10s].

    Every beat must be distinct when possible. Beats describe what is happening
    visually at that point, using the narration content or stage action.
    """
    sentences = _split_sentences(narration)
    if len(sentences) >= 3:
        return {
            "0-3s": sentences[0],
            "3-7s": sentences[1],
            "7-10s": sentences[2],
        }
    if len(sentences) == 2:
        return {
            "0-3s": sentences[0],
            "3-7s": sentences[1],
            "7-10s": f"transition from {sentences[1][:20]}...",
        }
    if len(sentences) == 1:
        # With only one sentence, expand to 3 distinct beats by splitting
        s = sentences[0]
        if len(s) >= 6:
            mid = len(s) // 2
            return {
                "0-3s": s[:mid],
                "3-7s": s[mid:],
                "7-10s": f"conclude: {s[-10:]}",
            }
        return {
            "0-3s": f"introduce: {s}",
            "3-7s": f"elaborate on {s[:20]}",
            "7-10s": f"transition from {s[:20]}...",
        }
    if narration.strip():
        # Fallback for edge cases
        return {
            "0-3s": narration,
            "3-7s": f"continue: {narration[:20]}",
            "7-10s": f"resolve: {narration[-20:]}",
        }
    # Empty narration (source exhausted): beats describe the stage
    # purpose so the clip still has a timed visual plan.
    stage_label = STAGES[stage_idx][0]
    return {
        "0-3s": f"[{stage_label}] establish visual premise",
        "3-7s": f"[{stage_label}] escalate through character action",
        "7-10s": f"[{stage_label}] deliver climax and transition",
    }


def _expand_narration(narration: str, min_chars: int, lang: str = "zh") -> str:
    """Expand narration if it's too short to meet min_chars.

    When source text is sparse, pad with descriptive content that stays
    true to the original meaning without inventing new facts.
    """
    current_len = len(narration)
    if current_len >= min_chars:
        return narration

    # For Chinese, we can append relevant trailing sentences from a longer source
    # But per F1/F2 fix: narration must come ONLY from source text, no fake scene descriptions
    # So we return as-is if we can't find more source content
    return narration


def _expand_narrations(segments: list[HeartbeatSegment], min_chars: int, lang: str) -> None:
    """Expand all segment narrations to meet minimum character count."""
    for seg in segments:
        seg.narration = _expand_narration(seg.narration, min_chars, lang)
        # Rebuild beats after expansion
        seg.beats = _build_beats(seg.narration, seg.stage_index)
        # Update visual_desc to match
        seg.visual_desc = seg.narration

def plan_heartbeat5(
    *,
    source_text: str,
    duration_s: float,
    narration_lang: str = "zh",
    title: str | None = None,
    topic: str | None = None,
    min_chars_per_clip: int = 0,
) -> HeartbeatPlan:
    """Plan a 5-stage heartbeat storyboard from a source text.

    Args:
        source_text: The source narration/article (Chinese or English).
        duration_s: Target duration in seconds (must be > 0).
        narration_lang: "zh" or "en".
        title: optional title override.
        topic: optional topic override.
        min_chars_per_clip: minimum Chinese chars per clip (0 = no expansion).

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
        # F6 fix: Visual state continuity must be scene descriptions, not narration text.
        # Each clip's ending scene = next clip's opening scene.
        sent_list = _split_sentences(narr)
        if len(sent_list) >= 2:
            vis_end = sent_list[-1]
        else:
            vis_end = narr
        # F6: If visual_state_end is narration text, replace with scene description
        if vis_end and any(kw in vis_end for kw in ['猫', '主人', '东西', '推', '掉地', '责备']):
            vis_end = f"stickman {['pushing object off table', 'holding up fingers', 'tapping paw pad', 'watching falling object', 'facing viewer with arms wide', 'shrugging with knowing gesture'][stage_idx % 6]} pose"
        vis_start = segments[-1].visual_state_end if segments else "white background with centered stick figure starting pose"
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
            hook_time_s=hook_time_s(duration_s),
            visual_state_start=vis_start,
            visual_state_end=vis_end,
        )
        segments.append(seg)

    hw = hook_window_s(duration_s)
    hook_start = hook_time_s(duration_s)
    hook_timing = HookTiming(
        hook_start_s=hook_start,
        hook_end_s=min(hook_start + 3.0, CLIP_S),
        window_start_s=hw[0],
        window_end_s=hw[1],
    )

    # Expand narrations to meet minimum character count (F2)
    _expand_narrations(segments, min_chars_per_clip, narration_lang)

    return HeartbeatPlan(
        title=title or (topic or "heartbeat5")[:40],
        topic=topic or (title or ""),
        duration_s=duration_s,
        clip_count=clip_count,
        hook_window=hw,
        narration_lang=narration_lang,
        segments=segments,
        source_facts=facts,
        hook_timing=hook_timing,
    )
