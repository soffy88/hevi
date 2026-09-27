"""HEVI P5.1 — speaker/evidence policy, information density, visual stagnation.

Covers §21-§28: semantic shot presentation, density balance, and stagnation that
is measured against *meaningful* change rather than raw movement.
"""

from __future__ import annotations

from hevi.ops.p5_1_presentation import (
    DECORATIVE_MOTION,
    MEANINGFUL_CHANGES,
    BeatSemantics,
    VisualChange,
    changes_from_decisions,
    check_motion_purpose,
    check_presentation_policy,
    decide_presentation,
    detect_visual_stagnation,
    evaluate_information_density,
    stagnation_issues,
    window_density,
)
from hevi.ops.p5_1_types import (
    EditorialIssueCategory,
    EvidenceVisibility,
    InformationDensity,
    ScaleLevel,
    ShotPresentationDecision,
    ShotPresentationRole,
    SpeakerVisibility,
)


def _semantics(
    beat_id: str,
    narration: str,
    *,
    shot_role: str = "EXPLAIN",
    phase: str = "DEVELOPMENT",
    gain: str = "NEW_DETAIL",
    motion: str = "FOCUS_DETAIL",
) -> BeatSemantics:
    return BeatSemantics(
        beat_id=beat_id,
        narration=narration,
        shot_role=shot_role,
        motion_purpose=motion,
        narrative_phase=phase,
        information_gain=gain,
    )


# ── test_speaker_evidence_policy ─────────────────────────────────────────


def test_speaker_evidence_policy_demo_beat_hides_the_speaker() -> None:
    """A beat whose job is to *show* something must not be a talking head."""
    beat = _semantics("b1", "这里显示官方文档的界面，我们来看第一步操作。")
    decision = decide_presentation(beat, speaker_available=True, evidence_available=True)
    assert decision.role in (
        ShotPresentationRole.DEMONSTRATION,
        ShotPresentationRole.EVIDENCE_DOMINANT,
    )
    assert decision.speaker_visibility is not SpeakerVisibility.DOMINANT
    assert decision.evidence_visibility is EvidenceVisibility.DOMINANT
    assert decision.evidence_scale is ScaleLevel.FULL_FRAME


def test_speaker_evidence_policy_direct_address_shows_the_speaker() -> None:
    beat = _semantics("b2", "说实话，我一开始也觉得这很难。", phase="HOOK", shot_role="REVEAL")
    decision = decide_presentation(beat, speaker_available=True)
    assert decision.role in (
        ShotPresentationRole.DIRECT_ADDRESS,
        ShotPresentationRole.EMOTIONAL_PRESENCE,
    )
    assert decision.speaker_visibility is SpeakerVisibility.DOMINANT


def test_speaker_evidence_policy_missing_evidence_is_flagged_not_faked() -> None:
    """No real evidence must not become a full-screen talking head."""
    beat = _semantics("b3", "这里显示官方文档的界面。")
    decision = decide_presentation(beat, speaker_available=True, evidence_available=False)
    assert decision.speaker_visibility is not SpeakerVisibility.DOMINANT
    assert "EVIDENCE_GAP" in decision.reason


def test_speaker_evidence_policy_never_uses_a_fixed_cadence() -> None:
    """Speaker visibility must follow semantics, not a ratio or an interval."""
    decisions = []
    beats = []
    script = [
        ("b1", "说实话，我一开始也觉得这很难。", "HOOK"),
        ("b2", "这里显示官方文档的界面。", "DEVELOPMENT"),
        ("b3", "我觉得关键在于这一点。", "DEVELOPMENT"),
        ("b4", "你可以看到导出按钮在这里。", "DEVELOPMENT"),
        ("b5", "总的来说，这套方法值得试试。", "PAYOFF"),
    ]
    for beat_id, narration, phase in script:
        beat = _semantics(beat_id, narration, phase=phase)
        beats.append(beat)
        decisions.append(
            decide_presentation(
                beat, speaker_available=True, evidence_available=True
            )
        )
    # A fixed "face every N seconds" policy would produce a constant ratio.
    ratios = [
        1.0 if d.speaker_visibility is SpeakerVisibility.DOMINANT else 0.0 for d in decisions
    ]
    assert len(set(ratios)) > 1, "speaker visibility must vary with beat semantics"
    assert check_presentation_policy(decisions, beats).ok


def test_presentation_policy_flags_speaker_overriding_evidence() -> None:
    beat = _semantics("b1", "这里显示官方文档的界面。")
    bad = ShotPresentationDecision(
        beat_id="b1",
        role=ShotPresentationRole.EVIDENCE_DOMINANT,
        speaker_visibility=SpeakerVisibility.DOMINANT,
        reason="forced",
    )
    report = check_presentation_policy([bad], [beat])
    assert not report.ok
    assert any("A8" in v for v in report.violations)


def test_presentation_policy_flags_hidden_speaker_on_direct_address() -> None:
    beat = _semantics("b2", "说实话，我一开始也觉得这很难。", phase="HOOK")
    bad = ShotPresentationDecision(
        beat_id="b2",
        role=ShotPresentationRole.DIRECT_ADDRESS,
        speaker_visibility=SpeakerVisibility.HIDDEN,
        reason="forced",
    )
    report = check_presentation_policy([bad], [beat])
    assert not report.ok
    assert any("A9" in v for v in report.violations)


def test_hidden_speaker_is_allowed_when_no_speaker_exists() -> None:
    beat = _semantics("b2", "说实话，我一开始也觉得这很难。", phase="HOOK")
    decision = decide_presentation(beat, speaker_available=False)
    assert decision.speaker_visibility is SpeakerVisibility.HIDDEN
    assert check_presentation_policy([decision], [beat]).ok


def test_presentation_decision_records_its_semantic_basis() -> None:
    beat = _semantics("b1", "我们来看导出设置。")
    decision = decide_presentation(beat, speaker_available=True, evidence_available=True)
    basis = decision.semantic_basis
    assert basis["shot_role"] == "EXPLAIN"
    assert basis["narrative_phase"] == "DEVELOPMENT"
    assert "evidence_beat" in basis
    assert decision.reason


# ── test_information_density ─────────────────────────────────────────────


def test_information_density_detects_too_empty() -> None:
    decision = ShotPresentationDecision(
        beat_id="b1",
        role=ShotPresentationRole.CONTEXTUAL_BROLL,
        speaker_visibility=SpeakerVisibility.HIDDEN,
        evidence_visibility=EvidenceVisibility.HIDDEN,
    )
    window = window_density(0, 1000, decision, caption_present=False, motion_present=False)
    assert window.density is InformationDensity.TOO_EMPTY


def test_information_density_detects_too_dense() -> None:
    decision = ShotPresentationDecision(
        beat_id="b1",
        role=ShotPresentationRole.DIRECT_ADDRESS,
        speaker_visibility=SpeakerVisibility.DOMINANT,
        evidence_visibility=EvidenceVisibility.DOMINANT,
        motion_priority=90,
    )
    window = window_density(
        0, 1000, decision, caption_present=True, overlay_present=True, sfx_present=True,
        caption_chars=30,
    )
    assert window.density is InformationDensity.TOO_DENSE
    assert len(window.competing_channels) >= 4


def test_information_density_balanced_window() -> None:
    decision = ShotPresentationDecision(
        beat_id="b1",
        role=ShotPresentationRole.EVIDENCE_DOMINANT,
        speaker_visibility=SpeakerVisibility.SMALL_PIP,
        evidence_visibility=EvidenceVisibility.DOMINANT,
        motion_priority=20,
    )
    window = window_density(0, 1000, decision, caption_present=True, caption_chars=12)
    assert window.density is InformationDensity.BALANCED


def test_information_density_evaluated_across_a_cut() -> None:
    decisions = [
        ShotPresentationDecision(
            beat_id=f"b{i}",
            role=ShotPresentationRole.EVIDENCE_DOMINANT
            if i % 2
            else ShotPresentationRole.DIRECT_ADDRESS,
            speaker_visibility=SpeakerVisibility.SMALL_PIP
            if i % 2
            else SpeakerVisibility.DOMINANT,
            evidence_visibility=EvidenceVisibility.DOMINANT if i % 2 else EvidenceVisibility.HIDDEN,
        )
        for i in range(4)
    ]
    windows = evaluate_information_density(
        decisions, captions_by_beat={f"b{i}": "text" for i in range(4)}
    )
    assert len(windows) == 4
    assert all(w.density in set(InformationDensity) for w in windows)


# ── test_visual_stagnation ───────────────────────────────────────────────


def test_visual_stagnation_detects_a_dead_span() -> None:
    """Gaps longer than the threshold are reported; short beats are not."""
    spans = detect_visual_stagnation(
        [
            VisualChange(0, 1000, "NEW_EVIDENCE"),
            VisualChange(1000, 2000, "ROLE_SWITCH"),
            VisualChange(2000, 3000, "SEMANTIC_HIGHLIGHT"),
            VisualChange(8000, 9000, "SHOT_CHANGE"),
        ],
        10.0,
    )
    assert len(spans) == 1
    assert spans[0].start_ms == 3000
    assert spans[0].end_ms == 8000
    assert spans[0].duration_s == 5.0


def test_visual_stagnation_leaves_short_gaps_alone() -> None:
    spans = detect_visual_stagnation(
        [VisualChange(1000, 2000, "NEW_EVIDENCE"), VisualChange(3000, 4000, "ROLE_SWITCH")],
        6.0,
    )
    assert spans == []


def test_visual_stagnation_ignores_decorative_motion() -> None:
    """Wiggling every second must not reset the stagnation clock."""
    changes = [
        VisualChange(1000, 2000, "BOUNCE"),
        VisualChange(2000, 3000, "WIGGLE"),
        VisualChange(3000, 4000, "RANDOM_ZOOM"),
        VisualChange(4000, 5000, "SPIN"),
    ]
    spans = detect_visual_stagnation(changes, 6.0)
    assert len(spans) == 1
    assert spans[0].duration_s == 6.0
    for change in changes:
        assert change.is_decorative
        assert not change.is_meaningful


def test_visual_stagnation_resets_on_meaningful_change() -> None:
    changes = [
        VisualChange(0, 1500, "NEW_EVIDENCE"),
        VisualChange(1500, 3000, "DIAGRAM_PROGRESSION"),
        VisualChange(3000, 4500, "COMPARISON_REVEAL"),
        VisualChange(4500, 6000, "SEMANTIC_HIGHLIGHT"),
    ]
    assert detect_visual_stagnation(changes, 6.0) == []


def test_visual_stagnation_is_not_a_mandatory_motion_rule() -> None:
    """A long, deliberate hold is not automatically a defect."""
    spans = detect_visual_stagnation([], 3.0, threshold_s=4.0)
    assert spans == []


def test_visual_stagnation_converts_to_locatable_issues() -> None:
    spans = detect_visual_stagnation([], 8.0)
    issues = stagnation_issues(spans)
    assert issues
    category, start_ms, end_ms, _ = issues[0]
    assert category is EditorialIssueCategory.VISUAL_STAGNATION
    assert end_ms > start_ms


def test_changes_are_derived_from_the_plan_not_invented() -> None:
    decisions = [
        ShotPresentationDecision(beat_id="b1", role=ShotPresentationRole.DIRECT_ADDRESS),
        ShotPresentationDecision(beat_id="b2", role=ShotPresentationRole.EVIDENCE_DOMINANT),
        ShotPresentationDecision(beat_id="b3", role=ShotPresentationRole.EVIDENCE_DOMINANT),
    ]
    decisions[1].evidence_visibility = EvidenceVisibility.DOMINANT
    changes = changes_from_decisions(decisions, evidence_beats={"b2"})
    kinds = {c.kind for c in changes}
    assert "ROLE_SWITCH" in kinds
    assert "NEW_EVIDENCE" in kinds
    # b3 repeats b2's role with no new evidence, so nothing is fabricated for it.
    assert all(c.beat_id != "b3" or c.kind == "SHOT_CHANGE" for c in changes)


def test_meaningful_and_decorative_vocabularies_are_disjoint() -> None:
    assert not (MEANINGFUL_CHANGES & DECORATIVE_MOTION)


def test_motion_purpose_rejects_decorative_repair() -> None:
    verdict = check_motion_purpose("add a bouncy wiggle so it feels more alive")
    assert verdict.accepted is False
    assert verdict.decorative is True


def test_motion_purpose_accepts_semantic_motion() -> None:
    beat = _semantics("b1", "看这里。", motion="FOCUS_DETAIL")
    verdict = check_motion_purpose(
        "FOCUS_DETAIL push onto the export control", beat=beat
    )
    assert verdict.accepted is True


def test_motion_purpose_rejects_unjustified_motion() -> None:
    verdict = check_motion_purpose("slow zoom in on the frame")
    assert verdict.accepted is False
    assert "MOTION_WITHOUT_SEMANTIC_PURPOSE" in verdict.reason
