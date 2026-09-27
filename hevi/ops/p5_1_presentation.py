"""HEVI P5.1 — shot presentation policy.

Decides, from *beat semantics alone*, how each VisualBeat should be presented:
who is visible, how big the evidence is, and how much attention captions and
motion should take.

The two hard rules this module exists to enforce:

* **Speaker visibility is semantic, never a cadence.** There is no "face every
  N seconds", no fixed 30% speaker ratio and no random picture-in-picture.
  ``A8`` (speaker always full screen despite a demo beat) and ``A9`` (speaker
  always hidden during an emotional direct address) are policy failures, and
  :func:`check_presentation_policy` reports them as such.
* **Visual change must mean something.** Stagnation is measured against
  *meaningful* change — new evidence, a role switch, a shot change, a semantic
  highlight, a diagram step, a purposeful push or a comparison reveal. Decorative
  bounce, random zoom and ornamental wiggle do not reset the stagnation clock,
  so a video cannot be "fixed" by animating everything.

Motion stays inside the existing component authority: this module selects
P1 ``MOTION_PURPOSES`` and existing semantic-motion primitives, and never
invents an arbitrary React motion system.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from hevi.ops.p5_1_types import (
    DensityWindow,
    EditorialIssueCategory,
    EvidenceVisibility,
    InformationDensity,
    ScaleLevel,
    ShotPresentationDecision,
    ShotPresentationRole,
    SpeakerVisibility,
    StagnationSpan,
)

# ── Narration semantics that drive direct address (§23) ──────────────────

#: The narration is doing opinion / trust / emotional connection / personal
#: judgement work. The speaker must be present.
DIRECT_ADDRESS_MARKERS = (
    "我认为",
    "我觉得",
    "我认为",
    "说实话",
    "坦白说",
    "我们都知道",
    "你有没有",
    "你应该",
    "别再",
    "不要",
    "我承认",
    "我害怕",
    "我希望",
    "我相信",
    "在我看来",
    "告诉你",
    "跟我看",
    "在今天这个",
    "如果你正在",
    "先别急",
    "很重要的一点",
    "我想说",
    "i think",
    "i believe",
    "honestly",
    "in my view",
    "you should",
    "stop",
    "listen",
)

#: The narration is proving / showing / operating / comparing something real.
EVIDENCE_DOMINANT_MARKERS = (
    "界面",
    "截图",
    "官网",
    "文档",
    "论文",
    "报告",
    "数据",
    "图表",
    "点击",
    "运行",
    "执行",
    "可以看到",
    "你会看到",
    "注意看",
    "这里显示",
    "版本",
    "发布",
    "对比",
    "相比",
    "接口",
    "dashboard",
    "screenshot",
    "interface",
    "click",
    "run",
    "compare",
    "docs",
    "chart",
)

DEMONSTRATION_MARKERS = (
    "我们来看",
    "演示",
    "操作一下",
    "跟着做",
    "第一步",
    "第二步",
    "这样设置",
    "打开设置",
    "let me show",
    "demo",
    "step one",
    "click here",
    "open settings",
)

EMOTIONAL_MARKERS = (
    "其实",
    "慢慢",
    "安静",
    "那一刻",
    "眼泪",
    "难过",
    "温柔",
    "记得",
    "有一天",
    "silently",
    "slowly",
    "one day",
    "i cried",
    "gentle",
)

_TRANSITION_MARKERS = ("接下来", "然后呢", "不过", "但是", "回到", "next", "but", "however")

_INFORMATION_MARKERS = (
    "数据",
    "图表",
    "统计",
    "报告",
    "参数",
    "数字",
    "百分比",
    "stats",
    "numbers",
    "percent",
    "chart",
    "table",
)

_CAPTION_CRITICAL_MARKERS = ("注意", "记住", "重点", "关键", "第一步", "第二点", "important", "note")


def _contains(text: str, markers: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


# ── Beat adapter (§25 — no duplicated beat type) ─────────────────────────


@dataclass
class BeatSemantics:
    """Read-only semantic view of a P1 ``VisualBeat``.

    P5.1 never redefines ``VisualBeat``; it reads the existing one through this
    narrow adapter so the P1/P2 chain stays the single source of beat truth.
    """

    beat_id: str
    narration: str = ""
    shot_role: str = ""
    motion_purpose: str = ""
    narrative_phase: str = ""
    information_gain: str = ""
    importance: float = 1.0
    semantic_action_type: str = ""
    semantic_subject: str = ""
    required_visual: str = ""
    preferred_visual: str = ""
    duration_s: float = 0.0
    has_real_evidence: bool = False
    evidence_asset_id: str = ""

    @classmethod
    def from_visual_beat(cls, beat: Any) -> BeatSemantics:
        """Adapt the canonical P1 VisualBeat without copying its definition."""
        action = getattr(beat, "semantic_action", None)
        start = float(getattr(beat, "timeline_start_s", 0.0) or 0.0)
        end = float(getattr(beat, "timeline_end_s", 0.0) or 0.0)
        requirements = getattr(beat, "asset_requirements", None) or []
        evidence_ids = [
            str(r.get("asset_id") or r.get("evidence_asset_id") or "")
            for r in requirements
            if isinstance(r, dict)
        ]
        evidence_ids = [e for e in evidence_ids if e]
        return cls(
            beat_id=str(getattr(beat, "beat_id", "")),
            narration=str(getattr(beat, "narration_span", "") or ""),
            shot_role=str(getattr(beat, "shot_role", "") or ""),
            motion_purpose=str(getattr(beat, "motion_purpose", "") or ""),
            narrative_phase=str(getattr(beat, "narrative_phase", "") or ""),
            information_gain=str(getattr(beat, "information_gain", "") or ""),
            importance=float(getattr(beat, "importance", 1.0) or 0.0),
            semantic_action_type=str(getattr(action, "action_type", "") or ""),
            semantic_subject=str(getattr(beat, "semantic_subject", "") or ""),
            required_visual=str(getattr(beat, "required_visual", "") or ""),
            preferred_visual=str(getattr(beat, "preferred_visual", "") or ""),
            duration_s=max(0.0, end - start),
            has_real_evidence=bool(evidence_ids),
            evidence_asset_id=evidence_ids[0] if evidence_ids else "",
        )


# ── Presentation decision (§22, §23, §24) ───────────────────────────────


def decide_presentation(
    semantics: BeatSemantics,
    *,
    profile_id: str = "",
    speaker_available: bool = True,
    evidence_available: bool | None = None,
) -> ShotPresentationDecision:
    """Decide one beat's presentation from its semantics.

    The order of judgement is deliberate: what the narration is *doing*
    (persuade vs. prove) outranks what assets happen to be available, so a demo
    beat is not silently turned into a talking head just because no screenshot
    was acquired yet.
    """
    text = semantics.narration
    has_evidence = (
        semantics.has_real_evidence if evidence_available is None else bool(evidence_available)
    )
    is_hook_or_payoff = semantics.narrative_phase in ("HOOK", "PAYOFF")
    is_demonstration = _contains(text, DEMONSTRATION_MARKERS)
    is_evidence_beat = _contains(text, EVIDENCE_DOMINANT_MARKERS) or is_demonstration
    is_direct = _contains(text, DIRECT_ADDRESS_MARKERS)
    is_emotional = _contains(text, EMOTIONAL_MARKERS) or semantics.narrative_phase in (
        "HOOK",
        "ORIENTATION",
    )
    wants_information = _contains(text, _INFORMATION_MARKERS)
    is_transition = semantics.shot_role == "TRANSITION" or _contains(text, _TRANSITION_MARKERS)
    speaker_needed = speaker_available and (is_direct or is_emotional or is_hook_or_payoff)

    # ── Role selection ──
    if is_transition and not speaker_needed:
        role = ShotPresentationRole.TRANSITION
    elif is_demonstration and has_evidence:
        role = ShotPresentationRole.DEMONSTRATION
    elif is_evidence_beat:
        role = ShotPresentationRole.EVIDENCE_DOMINANT
    elif is_emotional and not is_evidence_beat:
        role = ShotPresentationRole.EMOTIONAL_PRESENCE
    elif is_direct or is_hook_or_payoff:
        role = ShotPresentationRole.DIRECT_ADDRESS
    elif wants_information:
        role = ShotPresentationRole.FULL_SCREEN_INFORMATION
    else:
        role = ShotPresentationRole.CONTEXTUAL_BROLL

    # ── Speaker / evidence visibility ──
    if role in (ShotPresentationRole.DIRECT_ADDRESS, ShotPresentationRole.EMOTIONAL_PRESENCE):
        if not speaker_available:
            speaker_vis, speaker_scale = SpeakerVisibility.HIDDEN, ScaleLevel.NONE
        elif is_emotional and not is_hook_or_payoff:
            speaker_vis, speaker_scale = SpeakerVisibility.DOMINANT, ScaleLevel.LARGE
        else:
            speaker_vis, speaker_scale = SpeakerVisibility.DOMINANT, ScaleLevel.FULL_FRAME
        evidence_vis, evidence_scale = EvidenceVisibility.HIDDEN, ScaleLevel.NONE
    elif role in (ShotPresentationRole.EVIDENCE_DOMINANT, ShotPresentationRole.DEMONSTRATION):
        if has_evidence:
            speaker_vis = (
                SpeakerVisibility.SMALL_PIP if speaker_available else SpeakerVisibility.HIDDEN
            )
            speaker_scale = ScaleLevel.SMALL if speaker_available else ScaleLevel.NONE
        else:
            # The plan needs evidence that has not arrived. Do not fake it, and do
            # not quietly promote the speaker into the frame to fill it either:
            # a talking head standing in for a missing interface is exactly the
            # speaker-overuse failure §24 forbids. The honest result is an
            # evidence-dominant shot with an explicit evidence gap, which the
            # diagnosis layer turns into an EvidenceRequest.
            speaker_vis = SpeakerVisibility.SMALL_PIP if speaker_available else SpeakerVisibility.HIDDEN
            speaker_scale = ScaleLevel.SMALL if speaker_available else ScaleLevel.NONE
        evidence_vis = EvidenceVisibility.DOMINANT if has_evidence else EvidenceVisibility.HIDDEN
        evidence_scale = ScaleLevel.FULL_FRAME if has_evidence else ScaleLevel.NONE
    elif role is ShotPresentationRole.FULL_SCREEN_INFORMATION:
        speaker_vis = SpeakerVisibility.SMALL_PIP if speaker_available else SpeakerVisibility.HIDDEN
        speaker_scale = ScaleLevel.SMALL if speaker_available else ScaleLevel.NONE
        evidence_vis = EvidenceVisibility.DOMINANT
        evidence_scale = ScaleLevel.FULL_FRAME
    elif role is ShotPresentationRole.CONTEXTUAL_BROLL:
        speaker_vis = SpeakerVisibility.HIDDEN
        speaker_scale = ScaleLevel.NONE
        evidence_vis = EvidenceVisibility.VISIBLE if has_evidence else EvidenceVisibility.PARTIAL
        evidence_scale = ScaleLevel.MEDIUM if has_evidence else ScaleLevel.SMALL
    else:  # TRANSITION
        speaker_vis = SpeakerVisibility.HIDDEN
        speaker_scale = ScaleLevel.NONE
        evidence_vis = EvidenceVisibility.PARTIAL
        evidence_scale = ScaleLevel.SMALL

    # ── Attention priorities ──
    caption_priority = 50
    if _contains(text, _CAPTION_CRITICAL_MARKERS):
        caption_priority = 80
    if role in (ShotPresentationRole.DIRECT_ADDRESS, ShotPresentationRole.EMOTIONAL_PRESENCE):
        caption_priority = min(caption_priority, 55)  # restraint on emotional presence
    if role in (ShotPresentationRole.EVIDENCE_DOMINANT, ShotPresentationRole.DEMONSTRATION):
        caption_priority = max(caption_priority, 65)  # captions must not cover evidence

    motion_priority = 30
    if semantics.motion_purpose in ("FOCUS_DETAIL", "COMPARE_STATE", "SHOW_ORBIT"):
        motion_priority = 65
    if semantics.information_gain:
        motion_priority = max(motion_priority, 55)
    if role is ShotPresentationRole.EMOTIONAL_PRESENCE:
        motion_priority = min(motion_priority, 35)  # stillness can be the point

    reason = _reason_for(role, semantics, has_evidence, speaker_available)

    return ShotPresentationDecision(
        beat_id=semantics.beat_id,
        role=role,
        speaker_visibility=speaker_vis,
        speaker_scale=speaker_scale,
        evidence_visibility=evidence_vis,
        evidence_scale=evidence_scale,
        caption_priority=caption_priority,
        motion_priority=motion_priority,
        reason=reason,
        semantic_basis={
            "shot_role": semantics.shot_role,
            "motion_purpose": semantics.motion_purpose,
            "narrative_phase": semantics.narrative_phase,
            "information_gain": semantics.information_gain,
            "importance": semantics.importance,
            "direct_address": is_direct,
            "evidence_beat": is_evidence_beat,
            "demonstration": is_demonstration,
            "emotional": is_emotional,
            "has_real_evidence": has_evidence,
        },
    )


def _reason_for(
    role: ShotPresentationRole,
    semantics: BeatSemantics,
    has_evidence: bool,
    speaker_available: bool,
) -> str:
    base = f"role={role.value} from shot_role={semantics.shot_role}/phase={semantics.narrative_phase}"
    if role in (ShotPresentationRole.DIRECT_ADDRESS, ShotPresentationRole.EMOTIONAL_PRESENCE):
        if not speaker_available:
            return base + "; speaker unavailable so the shot cannot be direct address"
        return base + "; narration carries opinion/trust/emotion so the speaker must be present"
    if role in (ShotPresentationRole.EVIDENCE_DOMINANT, ShotPresentationRole.DEMONSTRATION):
        if not has_evidence:
            return base + "; EVIDENCE_GAP - real evidence required but not available"
        return base + "; narration proves/shows something so evidence dominates"
    return base


# ── Policy audit (§25, adversarial A8 / A9) ──────────────────────────────


@dataclass
class PresentationPolicyReport:
    """Result of auditing speaker/evidence decisions across a cut."""

    ok: bool = True
    violations: list[str] = field(default_factory=list)
    role_switches: int = 0
    speaker_dominant_beats: int = 0
    evidence_dominant_beats: int = 0
    evidence_gaps: int = 0
    speaker_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_presentation_policy(
    decisions: list[ShotPresentationDecision], semantics: list[BeatSemantics] | None = None
) -> PresentationPolicyReport:
    """Audit that speaker visibility follows semantics, not a fixed cadence.

    Rejects the two failure shapes that matter:

    * the speaker is full-screen on beats whose narration is proving something
      (``A8``);
    * the speaker is hidden on beats whose narration is a direct address to the
      viewer (``A9``).
    """
    report = PresentationPolicyReport()
    if not decisions:
        return report
    by_id = {s.beat_id: s for s in (semantics or [])}

    roles = [d.role for d in decisions]
    report.role_switches = sum(1 for a, b in itertools.pairwise(roles) if a is not b)
    report.speaker_dominant_beats = sum(
        1 for d in decisions if d.speaker_visibility is SpeakerVisibility.DOMINANT
    )
    report.evidence_dominant_beats = sum(
        1 for d in decisions if d.role in (ShotPresentationRole.EVIDENCE_DOMINANT,
                                          ShotPresentationRole.DEMONSTRATION)
    )
    report.speaker_ratio = report.speaker_dominant_beats / len(decisions)
    report.evidence_gaps = sum(1 for d in decisions if "EVIDENCE_GAP" in d.reason)

    for decision in decisions:
        beat = by_id.get(decision.beat_id)
        text = beat.narration if beat else ""

        evidence_role = decision.role in (
            ShotPresentationRole.EVIDENCE_DOMINANT,
            ShotPresentationRole.DEMONSTRATION,
        )
        if (
            evidence_role
            and decision.speaker_visibility is SpeakerVisibility.DOMINANT
            and not _contains(text, DIRECT_ADDRESS_MARKERS)
        ):
            report.violations.append(f"A8_SPEAKER_OVERRIDES_EVIDENCE:{decision.beat_id}")

        speaker_role = decision.role in (
            ShotPresentationRole.DIRECT_ADDRESS,
            ShotPresentationRole.EMOTIONAL_PRESENCE,
        )
        if (
            speaker_role
            and decision.speaker_visibility is SpeakerVisibility.HIDDEN
            and "speaker unavailable" not in decision.reason
        ):
            report.violations.append(
                f"A9_SPEAKER_HIDDEN_ON_DIRECT_ADDRESS:{decision.beat_id}"
            )

    # A cut that never changes role is a static cut; that is a stagnation problem
    # the stagnation detector owns, but a total absence of role variation is
    # worth surfacing here too.
    if len(decisions) >= 3 and report.role_switches == 0:
        report.violations.append("NO_SPEAKER_EVIDENCE_ROLE_VARIATION")

    report.ok = not report.violations
    return report


# ── Information density (§26) ────────────────────────────────────────────

#: Attention channels that can compete inside one window.
DENSITY_CHANNELS = ("speaker", "caption", "evidence", "overlay", "motion", "sfx")

#: At or above this many simultaneously salient channels a window is too dense.
TOO_DENSE_CHANNEL_COUNT = 4
#: At or below this many salient channels a window is too empty.
TOO_EMPTY_CHANNEL_COUNT = 1


def window_density(
    start_ms: int,
    end_ms: int,
    decision: ShotPresentationDecision,
    *,
    caption_present: bool = True,
    overlay_present: bool = False,
    motion_present: bool = True,
    sfx_present: bool = False,
    caption_chars: int = 0,
) -> DensityWindow:
    """Classify one window's information density.

    Density is a *conflict* measure, not an activity measure: five channels all
    shouting is worse than one channel speaking clearly.
    """
    channels: list[str] = []
    if decision.speaker_visibility in (SpeakerVisibility.DOMINANT, SpeakerVisibility.VISIBLE):
        channels.append("speaker")
    if caption_present and caption_chars:
        channels.append("caption")
    if decision.evidence_visibility in (EvidenceVisibility.DOMINANT, EvidenceVisibility.VISIBLE):
        channels.append("evidence")
    if overlay_present:
        channels.append("overlay")
    if motion_present and decision.motion_priority >= 50:
        channels.append("motion")
    if sfx_present:
        channels.append("sfx")

    count = len(channels)
    note = ""
    if count >= TOO_DENSE_CHANNEL_COUNT:
        density = InformationDensity.TOO_DENSE
        note = f"{count} channels competing: {','.join(channels)}"
    elif count <= TOO_EMPTY_CHANNEL_COUNT:
        density = InformationDensity.TOO_EMPTY
        note = f"only {count} salient channel(s): {','.join(channels) or 'none'}"
    else:
        density = InformationDensity.BALANCED
        note = f"{count} channels: {','.join(channels)}"

    return DensityWindow(
        start_ms=start_ms, end_ms=end_ms, density=density, competing_channels=channels, note=note
    )


def evaluate_information_density(
    decisions: list[ShotPresentationDecision],
    *,
    captions_by_beat: dict[str, str] | None = None,
    overlays_by_beat: dict[str, bool] | None = None,
    motion_by_beat: dict[str, bool] | None = None,
) -> list[DensityWindow]:
    """Evaluate density for every beat in a cut."""
    captions = captions_by_beat or {}
    overlays = overlays_by_beat or {}
    motion = motion_by_beat or {}
    windows: list[DensityWindow] = []
    for index, decision in enumerate(decisions):
        text = captions.get(decision.beat_id, "")
        windows.append(
            window_density(
                index * 1000,
                (index + 1) * 1000,
                decision,
                caption_present=bool(text),
                overlay_present=bool(overlays.get(decision.beat_id)),
                motion_present=bool(motion.get(decision.beat_id, True)),
                caption_chars=len(text),
            )
        )
    return windows


# ── Meaningful visual change (§28) ───────────────────────────────────────

#: A change that carries meaning and resets the stagnation clock.
MEANINGFUL_CHANGES = frozenset(
    {
        "NEW_EVIDENCE",
        "ROLE_SWITCH",
        "SHOT_CHANGE",
        "SEMANTIC_HIGHLIGHT",
        "DIAGRAM_PROGRESSION",
        "MEANINGFUL_PUSH",
        "COMPARISON_REVEAL",
    }
)

#: Motion that exists only to look busy. It is not meaningful change.
DECORATIVE_MOTION = frozenset(
    {"BOUNCE", "WIGGLE", "RANDOM_ZOOM", "DECORATIVE_PULSE", "SPIN", "FLOAT_IDLE"}
)


@dataclass
class VisualChange:
    """One change event on the timeline, classified by whether it means anything."""

    start_ms: int = 0
    end_ms: int = 0
    kind: str = ""
    beat_id: str = ""

    @property
    def is_meaningful(self) -> bool:
        return self.kind in MEANINGFUL_CHANGES

    @property
    def is_decorative(self) -> bool:
        return self.kind in DECORATIVE_MOTION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Default seconds of no meaningful change before a span counts as stagnant.
DEFAULT_STAGNATION_S = 4.0


def detect_visual_stagnation(
    changes: list[VisualChange],
    total_duration_s: float,
    *,
    threshold_s: float = DEFAULT_STAGNATION_S,
) -> list[StagnationSpan]:
    """Find spans with no meaningful visual change.

    Decorative motion is explicitly ignored: a cut that wobbles every second but
    never shows anything new is *more* stagnant than a still cut, not less. The
    rule is deliberately not "move every sentence" — the threshold is about
    sustained absence of meaning, and a still, well-held shot can be correct.
    """
    if total_duration_s <= 0:
        return []
    total_ms = int(total_duration_s * 1000)
    meaningful = sorted(
        (c for c in changes if c.is_meaningful), key=lambda c: (c.start_ms, c.end_ms)
    )

    spans: list[StagnationSpan] = []
    cursor = 0
    for change in meaningful:
        start = max(0, min(change.start_ms, total_ms))
        if start - cursor > threshold_s * 1000:
            spans.append(
                StagnationSpan(
                    start_ms=cursor,
                    end_ms=start,
                    duration_s=(start - cursor) / 1000.0,
                    reason="no meaningful visual change in this span",
                )
            )
        cursor = max(cursor, min(change.end_ms, total_ms))
    if total_ms - cursor > threshold_s * 1000:
        spans.append(
            StagnationSpan(
                start_ms=cursor,
                end_ms=total_ms,
                duration_s=(total_ms - cursor) / 1000.0,
                reason="no meaningful visual change in this span",
            )
        )
    return spans


def changes_from_decisions(
    decisions: list[ShotPresentationDecision],
    *,
    evidence_beats: set[str] | None = None,
    shot_changes_ms: list[tuple[int, int]] | None = None,
    highlight_beats: set[str] | None = None,
) -> list[VisualChange]:
    """Derive change events from presentation decisions.

    This is the honest version: a change is only recorded when the plan
    actually contains a role switch, a new piece of real evidence, or a real
    shot change. Nothing is invented to make a cut look alive.
    """
    evidence = evidence_beats or set()
    highlights = highlight_beats or set()
    events: list[VisualChange] = []
    previous_role: ShotPresentationRole | None = None
    for index, decision in enumerate(decisions):
        at = index * 1000
        if previous_role is not None and decision.role is not previous_role:
            events.append(
                VisualChange(start_ms=at, end_ms=at + 1000, kind="ROLE_SWITCH",
                             beat_id=decision.beat_id)
            )
        if decision.beat_id in evidence and decision.evidence_visibility in (
            EvidenceVisibility.DOMINANT,
            EvidenceVisibility.VISIBLE,
        ):
            events.append(
                VisualChange(start_ms=at, end_ms=at + 1000, kind="NEW_EVIDENCE",
                             beat_id=decision.beat_id)
            )
        if decision.beat_id in highlights:
            events.append(
                VisualChange(start_ms=at, end_ms=at + 1000, kind="SEMANTIC_HIGHLIGHT",
                             beat_id=decision.beat_id)
            )
        if decision.motion_priority >= 60:
            events.append(
                VisualChange(start_ms=at, end_ms=at + 1000, kind="MEANINGFUL_PUSH",
                             beat_id=decision.beat_id)
            )
        previous_role = decision.role
    for start, end in shot_changes_ms or []:
        events.append(
            VisualChange(start_ms=start, end_ms=end, kind="SHOT_CHANGE")
        )
    return sorted(events, key=lambda e: (e.start_ms, e.end_ms))


# ── Motion purpose (§28, adversarial A10) ────────────────────────────────

#: P1 motion purposes that are allowed to carry a repair.
_PURPOSEFUL_MOTIONS = frozenset(
    {
        "REVEAL_STRUCTURE",
        "FOLLOW_SUBJECT",
        "SHOW_ORBIT",
        "SHOW_COLLAPSE",
        "SHOW_SCALE",
        "FOCUS_DETAIL",
        "CONNECT_RELATIONSHIP",
        "COMPARE_STATE",
        "TRANSITION_CONTEXT",
    }
)

_DECORATIVE_MOTION_RE = re.compile(
    r"\b(bounce|wiggle|shake|pulse|jitter|spin|float|shake_it|bouncy|elastic_overshoot)\b",
    re.IGNORECASE,
)


@dataclass
class MotionVerdict:
    accepted: bool = True
    reason: str = ""
    suggested_purpose: str = ""
    decorative: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_motion_purpose(
    description: str,
    *,
    beat: BeatSemantics | None = None,
    motion_plans: list[Any] | None = None,
) -> MotionVerdict:
    """Reject a motion repair that adds movement without meaning.

    A repair that only decorates is refused, which is what keeps
    ``MOTION_PURPOSE`` a real gate rather than a style preference.
    """
    text = (description or "").strip()
    decorative_hit = _DECORATIVE_MOTION_RE.search(text)
    has_purpose = any(
        re.search(rf"\b{re.escape(p.lower())}\b", text.lower()) for p in _PURPOSEFUL_MOTIONS
    )
    if motion_plans:
        for plan in motion_plans:
            purpose = str(getattr(plan, "semantic_justification", "") or "")
            if purpose.strip():
                has_purpose = True
    if beat is not None and beat.motion_purpose in _PURPOSEFUL_MOTIONS and beat.information_gain:
        has_purpose = True

    if decorative_hit and not has_purpose:
        return MotionVerdict(
            accepted=False,
            reason=(
                f"DECORATIVE_MOTION_REJECTED:{decorative_hit.group(0)} adds movement "
                "without semantic purpose"
            ),
            decorative=True,
        )
    if not has_purpose:
        return MotionVerdict(
            accepted=False,
            reason="MOTION_WITHOUT_SEMANTIC_PURPOSE: no P1 motion purpose and no justification",
        )
    return MotionVerdict(
        accepted=True,
        reason="MOTION_SERVES_SEMANTIC_PURPOSE",
        suggested_purpose=beat.motion_purpose if beat else "",
    )


# ── Stagnation → editorial issues ────────────────────────────────────────


def stagnation_issues(
    spans: list[StagnationSpan],
) -> list[tuple[EditorialIssueCategory, int, int, str]]:
    """Turn stagnation spans into locatable editorial issue tuples."""
    return [
        (
            EditorialIssueCategory.VISUAL_STAGNATION,
            span.start_ms,
            span.end_ms,
            f"{span.duration_s:.1f}s with no meaningful visual change",
        )
        for span in spans
    ]


__all__ = [
    "DECORATIVE_MOTION",
    "DEFAULT_STAGNATION_S",
    "DEMONSTRATION_MARKERS",
    "DENSITY_CHANNELS",
    "DIRECT_ADDRESS_MARKERS",
    "EMOTIONAL_MARKERS",
    "EVIDENCE_DOMINANT_MARKERS",
    "MEANINGFUL_CHANGES",
    "TOO_DENSE_CHANNEL_COUNT",
    "TOO_EMPTY_CHANNEL_COUNT",
    "BeatSemantics",
    "MotionVerdict",
    "PresentationPolicyReport",
    "VisualChange",
    "changes_from_decisions",
    "check_motion_purpose",
    "check_presentation_policy",
    "decide_presentation",
    "detect_visual_stagnation",
    "evaluate_information_density",
    "stagnation_issues",
    "window_density",
]
