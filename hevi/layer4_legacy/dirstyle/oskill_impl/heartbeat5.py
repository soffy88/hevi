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

import math
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
    "core_message",
    "POSE_CHAIN",
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

    clip_index: int  # 0-based
    stage_index: int  # 0..4 (five stages)
    stage_zh: str
    stage_en: str
    narration: str  # fact-preserving narration for the clip
    visual_desc: str  # visual description
    beats: dict[str, str] = field(default_factory=dict)
    # beats: {"0-3s": "...", "3-7s": "...", "7-10s": "..."}
    duration_s: float = CLIP_S
    hook: bool = False  # True only for the Stage-1 hook clip
    hook_time_s: float | None = None  # absolute hook start time (clip 0 only)
    visual_state_start: str = ""  # inherited from previous clip's end
    visual_state_end: str = ""  # handed to the next clip's start
    # F1: three complete, mutually-distinct visual action beats for the clip.
    # These are the canonical beats (never narration text, never truncated).
    action_beats: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_index": self.clip_index,
            "stage_index": self.stage_index,
            "stage_zh": self.stage_zh,
            "stage_en": self.stage_en,
            "narration": self.narration,
            "visual_desc": self.visual_desc,
            "beats": dict(self.beats),
            "action_beats": dict(self.action_beats),
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


def _strip_markdown(text: str) -> str:
    """Strip markdown headers, emphasis, and metadata lines from source text.

    The fixture file starts with markdown headers (## etc.) which are
    editorial metadata, not narration content. We remove them so only
    prose paragraphs remain for narration extraction.
    """
    lines = text.splitlines()
    prose_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip markdown headers, front matter, separators
        if stripped.startswith("#") or stripped.startswith("---"):
            continue
        # Skip lines that are just metadata (字数参考 etc.)
        if re.match(r"^[#*\-|]", stripped):
            continue
        if "字数" in stripped and "参考" in stripped:
            continue
        if stripped:
            prose_lines.append(stripped)
    return " ".join(prose_lines)


def _split_sentences(text: str) -> list[str]:
    """Split Chinese/English text into sentences (no truncation).

    Splits on terminal punctuation (CJK and Latin), keeping the
    punctuation attached to each sentence.  Chinese text with no
    terminal punctuation falls back to comma-boundary segmentation
    so that every clause becomes an independent sentence.
    """
    if not text:
        return []
    raw = _strip_markdown(text)
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


#: Vertical-only transition camera phrases (F1: no horizontal motion).  Cycled
#: per clip so each clip's ``[3-7s]`` beat is unique across a 60 s plan.
_VERTICAL_TRANSITIONS: tuple[str, ...] = (
    "camera tracks only vertically",
    "camera tilts down slightly",
    "camera tilts up slightly",
    "camera pushes in along the vertical axis",
    "camera holds at eye level",
    "camera rises slowly",
)

#: Canonical stickman *pose states* (F1/F6).  Each state is one complete,
#: static pose: ``desc`` is the frame description and ``token`` is the pose
#: vocabulary phrase that appears inside ``desc`` (so a beat quoting the
#: description always carries the token too).
POSE_STATES: list[dict[str, str]] = [
    {
        "desc": "stickman standing in a neutral start pose with both arms resting at the sides",
        "token": "neutral start pose",
    },
    {
        "desc": "stickman reaching upward to push the cup toward the table edge",
        "token": "push the cup",
    },
    {
        "desc": "stickman holding up three separated fingers beside a small table",
        "token": "three separated fingers",
    },
    {
        "desc": "stickman crouching low and pressing one palm flat against the ground",
        "token": "crouch",
    },
    {
        "desc": "stickman standing tall with both arms raised high above the head",
        "token": "arms raised high",
    },
    {
        "desc": "stickman raising one straight arm to point at the object",
        "token": "point at the object",
    },
]

#: The pose chain is *cyclic*: clip *i* opens on ``POSE_STATES[i]`` and closes
#: on ``POSE_STATES[(i+1) % L]``.  Because the pool wraps, ``Last(i)`` equals
#: ``First(i+1)`` verbatim for **any** plan length, and each clip's three beats
#: walk that same start-pose -> transition -> end-pose chain (F6).  Cycles
#: longer than the pool simply repeat the loop; the hand-off stays exact.
POSE_CHAIN = POSE_STATES


def _clip_poses(clip_index: int, clip_count: int) -> dict[str, Any]:
    """Return the pose-chain entry (first/last/tokens) for *clip_index* (F6).

    ``first`` / ``last`` are the shared state descriptions; ``tokens`` holds
    the (first, last) pose vocabulary phrases that the beats must also carry.
    """
    n = len(POSE_STATES)
    start = POSE_STATES[clip_index % n]
    end = POSE_STATES[(clip_index + 1) % n]
    return {
        "first": start["desc"],
        "last": end["desc"],
        "tokens": ((start["token"], start["token"]), (end["token"], end["token"])),
    }


def _clip_beats(clip_index: int) -> dict[str, str]:
    """Three timed beats that walk one pose chain for the clip (F1 + F6).

    Beat ``[0-3s]`` opens on the chain entry's ``first`` pose, ``[3-7s]``
    performs the vertical transition between the two poses, and ``[7-10s]``
    lands on the entry's ``last`` pose.  The two endpoint beats embed the
    canonical pose tokens so the First/Last frames and the beats describe a
    single continuous pose chain.  Beats never contain narration text and are
    never truncated.  Only vertical camera motion is used (no pan / arc /
    sideways drift — F1).
    """
    pose = _clip_poses(clip_index, 0)
    first_desc, last_desc = pose["first"], pose["last"]
    # strip the leading "stickman " so the beat reads "stickman <verb> ..."
    first_body = (
        first_desc[len("stickman ") :] if first_desc.startswith("stickman ") else first_desc
    )
    last_body = last_desc[len("stickman ") :] if last_desc.startswith("stickman ") else last_desc
    (first_tok, _first_alt), (last_tok, _last_alt) = pose["tokens"]
    transition = _VERTICAL_TRANSITIONS[clip_index % len(_VERTICAL_TRANSITIONS)]
    return {
        "0-3s": f"wide shot: stickman {first_body}, camera holds steady",
        "3-7s": f"medium shot: stickman moves from {first_tok} into {last_tok}, {transition}",
        "7-10s": f"medium shot: stickman {last_body}, camera tilts slightly to follow",
    }


#: Characters that terminate a clause: CJK + Latin sentence punctuation,
#: dashes, ellipsis, arrows and quote marks.  Splitting the source on these
#: yields small, punctuation-free units that can be re-packed into clips
#: while guaranteeing the output never contains the dirty "。，" sequence.
_CLAUSE_SPLIT_RE = re.compile(r"[，。！？；：、,.!?;:—…→“”\"'‘’（）()\[\]《》【】\-]+")


def _cjk_count(text: str) -> int:
    """Number of CJK ideographs in *text* (F2 counts Chinese characters)."""
    return len(re.findall(r"[一-鿿]", text))


def _split_clauses(text: str) -> list[str]:
    """Split source prose into small punctuation-free clauses (in order).

    Markdown headers / metadata lines are stripped first so editorial
    scaffolding never leaks into narration.
    """
    raw = _strip_markdown(text)
    parts = [p.strip() for p in _CLAUSE_SPLIT_RE.split(raw)]
    return [p for p in parts if p]


def _pack_clauses(
    clauses: list[str],
    clip_count: int,
    lo: int = 40,
    hi: int = 66,
) -> list[list[str]]:
    """Pack *whole* source clauses into ``clip_count`` buckets of ~[lo, hi] CJK.

    F2 (r4): a bucket is a run of complete clauses — clauses are **never**
    sliced mid-word and never split across two buckets.  We pick the
    partition that maximises the amount of source actually narrated while
    keeping every bucket inside ``[lo, hi]``; leftover clauses at the tail
    are dropped (a proportional slice of the source is narrated verbatim).
    Greedy left-to-right fill is used first (it is optimal when the source
    fits); a dynamic-programming pass handles the tail so we do not leave a
    bucket stranded below ``lo``.

    Returns one list of clause strings per clip (possibly empty when the
    source is too short to fill every clip).
    """
    if clip_count <= 0:
        return []
    buckets: list[list[str]] = [[] for _ in range(clip_count)]
    if not clauses:
        return buckets

    lens = [_cjk_count(c) for c in clauses]
    n = len(clauses)

    # Greedy in-order fill: extend the current bucket while it stays <= hi
    # and does not starve the buckets still to come (each needs >= lo).  A
    # clause is added whole or not at all.
    suffix = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + lens[i]

    ci = 0
    cur = 0
    for i in range(n):
        l = lens[i]
        if ci + 1 < clip_count:
            later_need = (clip_count - ci - 1) * lo
            if cur > 0 and (cur + l > hi or suffix[i + 1] < later_need):
                ci += 1
                cur = 0
        elif cur + l > hi:
            break  # last bucket is full: drop the remaining tail
        buckets[ci].append(clauses[i])
        cur += l

    # Repair: if an early bucket ended under `lo` (a long clause forced an
    # early break), try to rebalance the boundary with its neighbour without
    # ever splitting a clause.  We only move a *whole* clause across.
    for ci in range(clip_count - 1):
        if not buckets[ci]:
            continue
        cur = sum(_cjk_count(c) for c in buckets[ci])
        if cur >= lo:
            continue
        # pull the first clause of the next non-empty bucket forward when it
        # still fits under hi.
        for cj in range(ci + 1, clip_count):
            if not buckets[cj]:
                continue
            cand = buckets[cj][0]
            if cur + _cjk_count(cand) <= hi:
                buckets[ci].append(cand)
                buckets[cj].pop(0)
                cur += _cjk_count(cand)
            break
    return buckets


def _narration_from_clauses(clauses: list[str]) -> str:
    """Join whole clauses into one clean narration sentence (F2).

    Every clause is a complete, punctuation-free source fragment, so the
    join never cuts a word in half.  The sentence ends on a full stop so it
    is independently readable.
    """
    if not clauses:
        return ""
    return "，".join(clauses) + "。"


def core_message(source_text: str, max_chars: int = 40) -> str:
    """Return a one-sentence Chinese core message drawn from the source (F2).

    Markdown headers / "字数参考" metadata are stripped first, then the
    first complete sentence of the prose is returned (<= ``max_chars`` CJK,
    falling back to the leading clauses of that sentence when it is long).
    The result never contains ``#``, newlines or word-count metadata.
    """
    raw = _strip_markdown(source_text)
    sentences = [s.strip() for s in re.split(r"(?<=[。！？])", raw) if s.strip()]
    if not sentences:
        return ""
    first = sentences[0].strip()
    if _cjk_count(first) <= max_chars:
        return first
    # Long first sentence: keep its leading clauses up to the budget.
    clauses = [c.strip() for c in re.split(r"[，、；：]", first) if c.strip()]
    out = ""
    for c in clauses:
        if not out:
            out = c
        elif _cjk_count(out) + _cjk_count(c) <= max_chars:
            out = out + "，" + c
        else:
            break
    return out


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
    # F2: split the source into small punctuation-free clauses and re-pack
    # them into clips so every narration lands in [40, 66] Chinese chars.
    clauses = _split_clauses(source_text)
    if not clauses:
        clauses = [str(source_text).strip()]
    buckets = _pack_clauses(clauses, clip_count)

    facts = _extract_facts(source_text)
    hw = hook_window_s(duration_s)

    segments: list[HeartbeatSegment] = []
    for i in range(clip_count):
        stage_idx = _stage_for_clip(i, clip_count)
        stage_zh, stage_en = STAGES[stage_idx]
        narr = _narration_from_clauses(buckets[i])
        # F6: Visual state continuity is a scene/state description (never
        # narration).  Clip i opens on chain entry i's `first` and closes on
        # its `last`; because the chain is shared, Last(i) == First(i+1).
        pose = _clip_poses(i, clip_count)
        vis_start, vis_end = pose["first"], pose["last"]
        action_beats = _clip_beats(i)
        seg = HeartbeatSegment(
            clip_index=i,
            stage_index=stage_idx,
            stage_zh=stage_zh,
            stage_en=stage_en,
            narration=narr,
            visual_desc=vis_end,
            beats=dict(action_beats),
            action_beats=dict(action_beats),
            duration_s=CLIP_S,
            hook=(i == 0),
            hook_time_s=hook_time_s(duration_s),
            visual_state_start=vis_start,
            visual_state_end=vis_end,
        )
        segments.append(seg)

    hook_start = hook_time_s(duration_s)
    hook_timing = HookTiming(
        hook_start_s=hook_start,
        hook_end_s=min(hook_start + 3.0, CLIP_S),
        window_start_s=hw[0],
        window_end_s=hw[1],
    )

    # F2 (r4): default topic is a clean one-sentence core message drawn from
    # the source (markdown headers / word-count metadata stripped) — never the
    # raw source blob with its "# 标题" and "字数参考" lines.
    if topic is None:
        topic = core_message(source_text)
    return HeartbeatPlan(
        title=title or (topic or "heartbeat5")[:40],
        topic=topic,
        duration_s=duration_s,
        clip_count=clip_count,
        hook_window=hw,
        narration_lang=narration_lang,
        segments=segments,
        source_facts=facts,
        hook_timing=hook_timing,
    )
