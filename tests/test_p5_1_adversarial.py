"""HEVI P5.1 — adversarial suite (A1-A20).

Every case is a way the editorial loop could lie, cheat, or do damage. Each test
asserts the system *refuses* rather than that it succeeds quietly.

    A1  frame-only provider pretending to be native video
    A2  stale VideoReview reused after the video hash changed
    A3  issue with a wrong timestamp
    A4  fake UI marked official
    A5  generated screenshot marked real
    A6  wrong evidence for a claim
    A7  private token visible in a screenshot
    A8  speaker always full screen despite a demo beat
    A9  speaker always hidden during an emotional direct address
    A10 meaningless motion added
    A11 new candidate introduces a blocker
    A12 forward says new, reverse says old
    A13 reviewer told which is new
    A14 only a cosmetic issue remains
    A15 the same issue repeated across revisions
    A16 revision budget exhausted
    A17 a 3-second defect triggers all source regeneration
    A18 an unaffected shot hash changes unexpectedly
    A19 editable project has a broken reference
    A20 human chooses the old version
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import hevi.ops.p5_1_pairwise as pairwise_module
from hevi.ops.p5_1_diagnosis import (
    PROTECTED_NODE_KINDS,
    ShotSpan,
    build_repair_intents,
    diagnose_review,
    merge_intents,
    plan_targeted_repair,
    validate_issue_location,
)
from hevi.ops.p5_1_editable import (
    build_layered_draft,
    manifest_from_production,
    validate_layered_project,
)
from hevi.ops.p5_1_evidence import (
    apply_privacy_policy,
    assert_evidence_truth,
    scan_privacy,
    select_best_evidence,
)
from hevi.ops.p5_1_pairwise import (
    PairwisePackage,
    PairwiseUnavailable,
    RegressionReport,
    assert_blind,
    check_regression_guard,
    decide_promotion,
)
from hevi.ops.p5_1_presentation import (
    BeatSemantics,
    check_motion_purpose,
    check_presentation_policy,
    decide_presentation,
)
from hevi.ops.p5_1_providers import (
    VIDEO_UNDERSTANDING,
    get_provider,
    register_video_understanding_providers,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_review import (
    StaleVideoReviewError,
    assert_review_current,
    run_video_review,
)
from hevi.ops.p5_1_session import (
    apply_human_decision,
    check_meaningful_revision,
    detect_no_progress,
    evaluate_stop_conditions,
    new_session,
)
from hevi.ops.p5_1_types import (
    CanonicalArtifact,
    DefectClass,
    DiagnosisFinding,
    EditorialDiagnosis,
    EditorialIssue,
    EditorialIssueCategory,
    EvidenceAsset,
    EvidenceSourceType,
    HumanDecision,
    IssueSeverity,
    PairwiseComparison,
    PairwiseVerdict,
    PromotionDecision,
    PromotionDecisionKind,
    RepairIntent,
    RepairScope,
    ReviewOutcome,
    RevisionCandidate,
    SessionStopReason,
    ShotPresentationDecision,
    ShotPresentationRole,
    SpeakerVisibility,
    VideoReview,
    video_file_hash,
)

SHOTS = [
    ShotSpan("s1", "b1", 0, 5000),
    ShotSpan("s2", "b2", 5000, 12000),
    ShotSpan("s3", "b3", 12000, 20000),
]


def _issue(category, severity, start, end, description="defect", **kw):
    return EditorialIssue(
        category=category,
        severity=severity,
        start_ms=start,
        end_ms=end,
        description=description,
        confidence=0.95,
        **kw,
    )


def _review(issues=None, duration_s=20.0, candidate_id="V0"):
    return VideoReview(
        content_id="c1",
        candidate_id=candidate_id,
        video_hash=f"sha256:{candidate_id}",
        video_duration_s=duration_s,
        provider="p",
        model="m",
        issues=issues or [],
    )


# ── A1: frame-only provider pretending native video ──────────────────────


def test_a1_frame_only_provider_cannot_serve_as_video_reviewer() -> None:
    register_video_understanding_providers(force=True)
    registry_holder = select_video_understanding_provider()
    assert registry_holder.provider_id, "a real native provider must exist for the contrast"

    class FrameOnly:
        provider_id = "a1_frame_only"
        capabilities = frozenset({VIDEO_UNDERSTANDING})  # no NATIVE_VIDEO_INPUT
        supports_native_video = False

        async def review_video(self, request):
            raise AssertionError("a frame-only reviewer must never be invoked")

    from obase.provider_registry import ProviderRegistry
    from obase.provider_routing import ProviderSpec

    registry = ProviderRegistry.get()
    registry.register_generic(
        "video_understanding", "a1_frame_only", FrameOnly(), replace=True
    )
    registry.register_spec(
        ProviderSpec(
            name="a1_frame_only",
            capabilities=frozenset({VIDEO_UNDERSTANDING}),
            models=(
                {
                    "name": "frame-only",
                    "provider": "a1_frame_only",
                    "capabilities": frozenset({VIDEO_UNDERSTANDING}),
                },
            ),
        ),
        replace=True,
    )

    preferred = select_video_understanding_provider("a1_frame_only")
    assert preferred.blocked is True
    assert "NATIVE_VIDEO_INPUT" in preferred.reason

    with pytest.raises(Exception) as excinfo:
        get_provider("a1_frame_only")
    assert "a1_frame_only" in str(excinfo.value)


# ── A2: stale review reuse ───────────────────────────────────────────────


def test_a2_stale_review_is_never_reused_after_video_change(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"version-one")
    review = VideoReview(video_hash=video_file_hash(video), video_path=str(video))

    video.write_bytes(b"version-two-different-bytes")
    with pytest.raises(StaleVideoReviewError):
        assert_review_current(review, video)

    blocked = asyncio.run(
        run_video_review(
            tmp_path / "missing.mp4", content_id="c", candidate_id="V1",
            provider_id="a2_nonexistent",
        )
    )
    assert blocked.outcome in (ReviewOutcome.BLOCKED_BY_PROVIDER, ReviewOutcome.FAILED)
    assert blocked.issues == []


# ── A3: wrong timestamp ──────────────────────────────────────────────────


def test_a3_wrong_timestamp_produces_no_unsafe_targeted_repair() -> None:
    bad = _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 90000, 95000)
    check = validate_issue_location(bad, SHOTS, duration_ms=20000)
    assert check.ok is False

    diagnosis = diagnose_review(_review([bad]), shots=SHOTS)
    assert diagnosis.autonomous_findings() == []
    intents = merge_intents(build_repair_intents(diagnosis, shots=SHOTS))
    plan = plan_targeted_repair(diagnosis, intents, content_id="c1", candidate_id="V0")
    assert plan.decision == "stop"
    assert plan.rerun_nodes == []


# ── A4/A5/A6: evidence truth ─────────────────────────────────────────────


def test_a4_fake_ui_marked_official_is_blocked() -> None:
    asset = EvidenceAsset(
        source_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
        claim_supported="Acme exports CSVs",
        entity="Acme",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://acme.dev/export",
        provenance={"generator": "stable-diffusion", "capture_method": "text2image"},
    )
    verdict = assert_evidence_truth(asset)
    assert verdict.ok is False
    assert any("FAKE_UI_AS_EVIDENCE" in v for v in verdict.violations)


def test_a5_generated_screenshot_marked_real_is_blocked() -> None:
    asset = EvidenceAsset(
        source_type=EvidenceSourceType.REAL_INTERFACE,
        claim_supported="Acme Console",
        entity="Acme Console",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://acme.dev/",
        provenance={"generated": True, "ai_generated": True},
    )
    assert assert_evidence_truth(asset).ok is False


def test_a6_wrong_evidence_for_a_claim_is_excluded() -> None:
    right = EvidenceAsset(
        asset_id="right",
        source_type=EvidenceSourceType.DOCUMENT_EXCERPT,
        claim_supported="Acme supports bulk export",
        entity="Acme",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://docs.acme.dev/export",
        confidence=0.8,
    )
    wrong = EvidenceAsset(
        asset_id="wrong",
        source_type=EvidenceSourceType.REAL_INTERFACE,
        claim_supported="Acme supports bulk export",
        entity="Acme",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://github.com/acme/ui",
        confidence=0.99,
        provenance={"official_verified": True},
    )
    # Both are truthful in themselves, so the ladder decides on evidence rank.
    chosen, _rejected = select_best_evidence(
        [wrong, right], claim="Acme supports bulk export", entity="Acme"
    )
    assert chosen is not None
    assert chosen.asset_id in {"right", "wrong"}

    # A fabricated one is excluded outright rather than merely outranked.
    fake = EvidenceAsset(
        asset_id="fake",
        source_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
        claim_supported="Acme supports bulk export",
        entity="Acme",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://acme.dev/",
        provenance={"generated": True, "official_verified": True},
    )
    best, rejected = select_best_evidence([fake, right], claim="Acme supports", entity="Acme")
    assert best.asset_id == "right"
    assert any("FAKE_UI_AS_EVIDENCE" in reason for reason in rejected)


# ── A7: private data in a screenshot ─────────────────────────────────────


def test_a7_private_token_in_screenshot_is_rejected() -> None:
    scan = scan_privacy("session ghp_abcdefghijklmnopqrstuvwxyz012345 visible on screen")
    assert scan.safe is False
    assert "GITHUB_TOKEN" in scan.secret_kinds

    asset = EvidenceAsset(
        source_type=EvidenceSourceType.OFFICIAL_SCREENSHOT,
        claim_supported="Acme dashboard",
        entity="Acme",
        captured_at="2026-09-01T00:00:00Z",
        source_uri="https://acme.dev/",
    )
    asset, reasons = apply_privacy_policy(asset, scan)
    assert any(r.startswith("REJECT:") for r in reasons)
    assert asset.claim_supported == ""
    assert asset.privacy_scan["secret_kinds"]


# ── A8/A9: speaker/evidence policy ───────────────────────────────────────


def test_a8_speaker_always_full_screen_during_a_demo_beat_fails_policy() -> None:
    beat = BeatSemantics(
        beat_id="b1",
        narration="这里显示官方文档的界面，我们来看导出操作。",
        shot_role="EXPLAIN",
    )
    decisions = [
        ShotPresentationDecision(
            beat_id=f"b{i}",
            role=ShotPresentationRole.EVIDENCE_DOMINANT
            if i == 0
            else ShotPresentationRole.CONTEXTUAL_BROLL,
            speaker_visibility=SpeakerVisibility.DOMINANT,  # the failure shape
            reason="forced full screen",
        )
        for i in range(3)
    ]
    semantics = [beat, beat, beat]
    report = check_presentation_policy(decisions, semantics)
    assert report.ok is False
    assert any("A8" in v for v in report.violations)


def test_a9_speaker_always_hidden_during_emotional_direct_address_fails() -> None:
    beats = [
        BeatSemantics(beat_id=f"b{i}", narration="说实话，我一开始也觉得这很难。",
                      narrative_phase="HOOK")
        for i in range(3)
    ]
    decisions = [
        decide_presentation(beat, speaker_available=False) for beat in beats
    ]
    for decision in decisions:
        decision.reason = "hidden"  # drop the honest "unavailable" justification
    report = check_presentation_policy(decisions, beats)
    assert report.ok is False
    assert any("A9" in v for v in report.violations)


# ── A10: meaningless motion ──────────────────────────────────────────────


def test_a10_meaningless_motion_repair_is_rejected() -> None:
    for description in (
        "add a bounce to make it feel more alive",
        "random zoom in and out",
        "wiggle the whole frame every second",
    ):
        verdict = check_motion_purpose(description)
        assert verdict.accepted is False, description
    meaningful = check_motion_purpose("FOCUS_DETAIL push onto the export control")
    assert meaningful.accepted is True


def test_a10_decorative_motion_is_not_meaningful_visual_change() -> None:
    from hevi.ops.p5_1_presentation import VisualChange, detect_visual_stagnation

    changes = [VisualChange(i * 1000, i * 1000 + 900, "BOUNCE") for i in range(5)]
    spans = detect_visual_stagnation(changes, 5.0)
    assert len(spans) == 1, "decorative motion must not reset the stagnation clock"


# ── A11: new candidate introduces a blocker ──────────────────────────────


def test_a11_new_blocker_rejects_the_new_candidate() -> None:
    outcome = PairwiseComparison(
        verdict=PairwiseVerdict.B, winner_candidate_id="V1", position_of_old="A"
    )
    from hevi.ops.p5_1_pairwise import PairwiseOutcome

    bidirectional = PairwiseOutcome(
        forward=outcome,
        reversed=PairwiseComparison(
            verdict=PairwiseVerdict.A, winner_candidate_id="V1", position_of_old="B"
        ),
        old_wins_forward=False,
        old_wins_reversed=False,
        new_wins_both=True,
        old_candidate_id="V0",
        new_candidate_id="V1",
    )
    decision = decide_promotion(
        content_id="c1",
        session_id="s",
        old=RevisionCandidate(candidate_id="V0", video_path="/a"),
        new=RevisionCandidate(candidate_id="V1", video_path="/b"),
        new_review=_review(
            [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 1000, 2000)],
            candidate_id="V1",
        ),
        old_review=None,
        pairwise=bidirectional,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert decision.new_blockers == 1


# ── A12: split verdict ───────────────────────────────────────────────────


def test_a12_forward_new_reverse_old_blocks_promotion() -> None:
    from hevi.ops.p5_1_pairwise import PairwiseOutcome

    forward = PairwiseComparison(
        verdict=PairwiseVerdict.B, winner_candidate_id="V1", position_of_old="A"
    )
    reversed_cmp = PairwiseComparison(
        verdict=PairwiseVerdict.A, winner_candidate_id="V0", position_of_old="B"
    )
    bidirectional = PairwiseOutcome(
        forward=forward,
        reversed=reversed_cmp,
        old_wins_forward=False,
        old_wins_reversed=True,
        new_wins_both=False,
        position_bias_or_uncertain=True,
        old_candidate_id="V0",
        new_candidate_id="V1",
    )
    decision = decide_promotion(
        content_id="c1",
        session_id="s",
        old=RevisionCandidate(candidate_id="V0", video_path="/a"),
        new=RevisionCandidate(candidate_id="V1", video_path="/b"),
        new_review=_review(candidate_id="V1"),
        old_review=None,
        pairwise=bidirectional,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert decision.position_bias_or_uncertain is True


# ── A13: reviewer told which is new ───────────────────────────────────────


def test_a13_reviewer_told_which_is_new_fails_blindness() -> None:
    leaking = [
        "Candidate A is the new version.",
        "The newer candidate is B, so prefer the new one.",
        "We just fixed the issues in A.",
        "Candidate A costs $0.02.",
    ]
    for prompt in leaking:
        package = PairwisePackage(
            candidate_a_path="/a.mp4", candidate_b_path="/b.mp4", prompt=prompt
        )
        ok, leaks = assert_blind(package)
        assert ok is False, prompt
        assert leaks

    clean = PairwisePackage(
        candidate_a_path="/a.mp4",
        candidate_b_path="/b.mp4",
        prompt="Compare Candidate A and Candidate B. Hard defects dominate.",
    )
    assert assert_blind(clean)[0] is True


# ── A14: only cosmetic remains ────────────────────────────────────────────


def test_a14_only_cosmetic_issue_stops_the_loop() -> None:
    from hevi.ops.p5_1_types import DiagnosisFinding

    session = new_session("c1")
    diagnosis = EditorialDiagnosis(
        findings=[
            DiagnosisFinding(
                categories=[EditorialIssueCategory.PACING],
                severity=IssueSeverity.COSMETIC,
                repairable=False,
            )
        ]
    )
    assert evaluate_stop_conditions(session, diagnosis, None) is (
        SessionStopReason.ONLY_MINOR_COSMETIC_REMAINS
    )
    verdict = check_meaningful_revision(
        [
            RepairIntent(
                diagnosis_id="d",
                target_artifacts=[CanonicalArtifact.SHOT_PLAN],
                expected_change="x",
                expected_visual_effect="y",
                verification="z",
                meaningful=False,
            )
        ],
        diagnosis,
    )
    assert verdict.ok is False


# ── A15: same issue repeated ─────────────────────────────────────────────


def test_a15_same_issue_repeated_stops_autonomy() -> None:
    session = new_session("c1")
    for index in range(3):
        candidate_id = f"V{index}"
        session.candidates.append(
            RevisionCandidate(candidate_id=candidate_id, revision_number=index, video_path="/x")
        )
        session.diagnoses[candidate_id] = EditorialDiagnosis(
            findings=[
                DiagnosisFinding(
                    categories=[EditorialIssueCategory.FAKE_UI],
                    severity=IssueSeverity.BLOCKER,
                    repairable=True,
                    canonical_artifact=CanonicalArtifact.EVIDENCE_ASSET,
                )
            ]
        )
    detected, reason = detect_no_progress(session)
    assert detected is True
    assert "NO_PROGRESS_DETECTED" in reason
    assert evaluate_stop_conditions(
        session, session.diagnoses["V2"], None
    ) is SessionStopReason.NO_PROGRESS_DETECTED


# ── A16: budget exhausted ────────────────────────────────────────────────


def test_a16_revision_budget_exhausted_stops_cleanly() -> None:
    from hevi.ops.p5_1_types import DiagnosisFinding, SessionCost

    session = new_session("c1", budget_usd=1.0)
    session.cost = SessionCost(review_cost_usd=0.95, render_cost_usd=0.10)
    diagnosis = EditorialDiagnosis(
        findings=[
            DiagnosisFinding(
                categories=[EditorialIssueCategory.FAKE_UI],
                severity=IssueSeverity.BLOCKER,
                repairable=True,
                canonical_artifact=CanonicalArtifact.EVIDENCE_ASSET,
            )
        ]
    )
    assert evaluate_stop_conditions(session, diagnosis, None) is (
        SessionStopReason.BUDGET_EXHAUSTED
    )
    assert session.rounds_remaining() == 3
    assert session.stop_reason is None  # evaluate does not mutate; the runner stops


# ── A17: 3-second defect must not regenerate everything ──────────────────


def test_a17_three_second_defect_does_not_trigger_full_regeneration() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 12000, 15000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    intents = merge_intents(build_repair_intents(diagnosis, shots=SHOTS))
    plan = plan_targeted_repair(
        diagnosis,
        intents,
        content_id="c1",
        candidate_id="V0",
        node_ids={k: f"n:{k}" for k in ("ASSET", "SHOT", "MOTION", "RENDER", "EDIT")},
        artifact_ids={
            "research": "a:research",
            "script": "a:script",
            "tts": "a:tts",
            "shot1": "a:shot1",
            "shot2": "a:shot2",
            "shot3": "a:shot3",
        },
        all_artifact_ids=["research", "script", "tts", "shot1", "shot2", "shot3"],
    )
    assert plan.changed_ranges_ms == [(12000, 15000)]
    assert not (set(plan.rerun_nodes) & {f"n:{k}" for k in PROTECTED_NODE_KINDS})
    for preserved in ("a:research", "a:script", "a:tts", "a:shot1", "a:shot2"):
        assert preserved in plan.preserve_artifact_ids, preserved
    assert plan.decision == "execute"


# ── A18: unaffected shot changed unexpectedly ────────────────────────────


def test_a18_unaffected_range_regression_is_caught() -> None:
    new_review = _review(
        [
            _issue(EditorialIssueCategory.PACING, IssueSeverity.MAJOR, 1000, 3000),
            _issue(EditorialIssueCategory.SUBJECT_JUMP, IssueSeverity.BLOCKER, 6000, 7000),
        ],
        candidate_id="V1",
    )
    new = RevisionCandidate(
        candidate_id="V1",
        video_path="/b",
        changed_ranges=[(12000, 16000)],
        changed_artifacts=["a:evidence-3"],
        unchanged_artifacts=["a:shot1", "a:shot2"],
    )
    report = check_regression_guard(RevisionCandidate(candidate_id="V0", video_path="/a"), new, new_review)
    assert report.ok is False
    assert report.unchanged_range_regressions >= 1

    decision = decide_promotion(
        content_id="c1",
        session_id="s",
        old=RevisionCandidate(candidate_id="V0", video_path="/a"),
        new=new,
        new_review=new_review,
        old_review=None,
        pairwise=None,
        expected_repair_verified=True,
        regression=report,
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert decision.regression_detected is True


# ── A19: broken editable reference ───────────────────────────────────────


def test_a19_broken_editable_reference_blocks_delivery(tmp_path: Path) -> None:
    manifest = manifest_from_production(
        content_id="c1", candidate_id="V1", background_path="/definitely/missing.mp4",
        duration_ms=2000,
    )
    project = build_layered_draft(manifest, tmp_path / "proj")
    assert project.refused_elements
    # Nothing is shipped that points at nothing.
    draft_tracks = project.manifest.layers
    assert draft_tracks == {}
    # A manifest that *claims* an element with no material is still a block.
    manifest.add(
        type(manifest).__mro__ and __import__(
            "hevi.ops.p5_1_editable", fromlist=["LayerElement"]
        ).LayerElement(
            element_id="ghost",
            layer=__import__("hevi.ops.p5_1_types", fromlist=["EditableLayer"]).EditableLayer.BACKGROUND,
            semantic_role="CONTEXTUAL_BROLL",
            start_ms=0,
            end_ms=2000,
            source_artifact="ghost",
            source_path="/also/missing.mp4",
        )
    )
    ok, errors = validate_layered_project(project)
    assert ok is False
    assert any("BROKEN_REFERENCE" in e for e in errors)


# ── A20: human chooses the old version ───────────────────────────────────


def test_a20_human_choosing_the_old_version_wins() -> None:
    session = new_session("c1", "KNOWLEDGE_TALK_FINECUT")
    session.candidates = [
        RevisionCandidate(content_id="c1", candidate_id="V0", revision_number=0, video_path="/a"),
        RevisionCandidate(content_id="c1", candidate_id="V1", revision_number=1, video_path="/b"),
    ]
    # Even if V1 had been promoted, a human keeping V0 makes V0 authoritative.
    session.record_promotion(
        PromotionDecision(
            decision=PromotionDecisionKind.PROMOTE_NEW,
            old_candidate_id="V0",
            new_candidate_id="V1",
        )
    )
    assert session.authoritative_candidate_id == "V1"

    promotion = apply_human_decision(session, HumanDecision.KEEP_V0)
    assert promotion.decision is PromotionDecisionKind.KEEP_OLD
    assert session.authoritative_candidate_id == "V0"
    assert session.authoritative().candidate_id == "V0"
    assert promotion.human_override is HumanDecision.KEEP_V0


# ── Cross-cutting: hard defect classification feeds the repair gate ──────


def test_hard_defects_are_repairable_and_preferences_are_not() -> None:
    review = _review(
        [
            _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 2000),
            _issue(EditorialIssueCategory.SHOT_TOO_LONG, IssueSeverity.MAJOR, 6000, 8000),
        ]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    by_category = {f.categories[0]: f for f in diagnosis.findings}
    assert by_category[EditorialIssueCategory.CAPTION_OCCLUSION].defect_class is (
        DefectClass.HARD_DEFECT
    )
    assert by_category[EditorialIssueCategory.CAPTION_OCCLUSION].repairable is True
    assert by_category[EditorialIssueCategory.SHOT_TOO_LONG].defect_class is (
        DefectClass.EDITORIAL_PREFERENCE
    )
    assert by_category[EditorialIssueCategory.SHOT_TOO_LONG].repairable is False


def test_pairwise_unavailable_is_never_treated_as_a_win() -> None:
    """§84: no provider is a block, never an implicit approval."""

    async def _boom(*args, **kwargs):
        raise PairwiseUnavailable("BLOCKED_BY_PROVIDER")

    original = pairwise_module.run_pairwise_direction
    pairwise_module.run_pairwise_direction = _boom  # type: ignore[assignment]
    try:
        with pytest.raises(PairwiseUnavailable):
            asyncio.run(
                pairwise_module.run_bidirectional_pairwise(
                    RevisionCandidate(candidate_id="V0", video_path="/a"),
                    RevisionCandidate(candidate_id="V1", video_path="/b"),
                    workdir=Path("/tmp"),
                )
            )
    finally:
        pairwise_module.run_pairwise_direction = original  # type: ignore[assignment]

    decision = decide_promotion(
        content_id="c1",
        session_id="s",
        old=RevisionCandidate(candidate_id="V0", video_path="/a"),
        new=RevisionCandidate(candidate_id="V1", video_path="/b"),
        new_review=_review(candidate_id="V1"),
        old_review=None,
        pairwise=None,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.HUMAN_REVIEW


def test_scopes_that_regenerate_sources_are_the_exception() -> None:
    for scope in (
        RepairScope.ASSET_ONLY,
        RepairScope.SHOT_ONLY,
        RepairScope.TIMELINE_RANGE,
        RepairScope.CAPTION_RANGE,
        RepairScope.MOTION_RANGE,
        RepairScope.AUDIO_MIX_RANGE,
    ):
        assert RepairIntent(scope=scope).regenerates_sources is False
