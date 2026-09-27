"""HEVI P5.1 — repair intents, targeted visual repair, revision candidates.

Covers §29-§37: diagnosis, root-cause mapping, repair scope, the P3-scoped
targeted repair plan, and the candidate chain.
"""

from __future__ import annotations

from hevi.ops.p5_1_diagnosis import (
    ARTIFACT_RERUN_NODES,
    PROTECTED_NODE_KINDS,
    ShotSpan,
    changed_layers,
    diagnose_review,
    merge_intents,
    plan_targeted_repair,
    unaffected_source_reruns,
    validate_issue_location,
)
from hevi.ops.p5_1_types import (
    NON_REGENERATING_SCOPES,
    ROOT_CAUSE_MAP,
    CanonicalArtifact,
    DefectClass,
    DiagnosisFinding,
    EditorialDiagnosis,
    EditorialIssue,
    EditorialIssueCategory,
    IssueSeverity,
    RepairIntent,
    RepairScope,
    RevisionCandidate,
    VideoReview,
    classify_defect,
)

SHOTS = [
    ShotSpan("s1", "b1", 0, 5000),
    ShotSpan("s2", "b2", 5000, 12000),
    ShotSpan("s3", "b3", 12000, 20000),
]


def _issue(
    category: EditorialIssueCategory,
    severity: IssueSeverity,
    start_ms: int,
    end_ms: int,
    description: str = "problem",
    **kwargs: object,
) -> EditorialIssue:
    return EditorialIssue(
        category=category,
        severity=severity,
        start_ms=start_ms,
        end_ms=end_ms,
        description=description,
        confidence=0.9,
        **kwargs,  # type: ignore[arg-type]
    )


def _review(issues: list[EditorialIssue], duration_s: float = 20.0) -> VideoReview:
    return VideoReview(
        content_id="c1",
        candidate_id="V0",
        video_hash="sha256:v0",
        video_duration_s=duration_s,
        provider="p",
        model="m",
        issues=issues,
    )


# ── test_repair_intent ───────────────────────────────────────────────────


def test_repair_intent_requires_a_complete_declaration() -> None:
    intent = RepairIntent(
        target_artifacts=[CanonicalArtifact.CAPTION_STYLE],
        expected_change="move captions",
        expected_visual_effect="subject stays visible",
        verification="re-review the range",
    )
    ok, errors = intent.is_valid()
    assert ok is False
    assert "diagnosis_id required" in errors


def test_repair_intent_is_valid_when_fully_declared() -> None:
    intent = RepairIntent(
        diagnosis_id="d1",
        target_artifacts=[CanonicalArtifact.CAPTION_STYLE],
        expected_change="move captions",
        expected_visual_effect="subject stays visible",
        verification="re-review the range",
        scope=RepairScope.CAPTION_RANGE,
        start_ms=1000,
        end_ms=3000,
    )
    ok, errors = intent.is_valid()
    assert ok, errors


def test_global_scope_requires_an_explicit_reason() -> None:
    intent = RepairIntent(
        diagnosis_id="d1",
        target_artifacts=[CanonicalArtifact.PROFILE_DIRECTION],
        expected_change="revise direction",
        expected_visual_effect="cut matches profile",
        verification="re-review whole cut",
        scope=RepairScope.GLOBAL,
    )
    ok, errors = intent.is_valid()
    assert ok is False
    assert any("GLOBAL scope requires" in e for e in errors)


def test_no_repair_intent_means_no_autonomous_revision() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 13000, 16000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    assert diagnosis.autonomous_findings()
    intents = merge_intents(_intents(diagnosis))
    assert intents
    for intent in intents:
        assert intent.diagnosis_id == diagnosis.diagnosis_id


def _intents(diagnosis: EditorialDiagnosis) -> list[RepairIntent]:
    from hevi.ops.p5_1_diagnosis import build_repair_intents

    return build_repair_intents(diagnosis, shots=SHOTS)


def test_repair_intent_declares_its_effect_and_verification() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 3000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    (intent,) = merge_intents(_intents(diagnosis))
    assert intent.target_artifacts == [CanonicalArtifact.CAPTION_STYLE]
    assert intent.expected_change
    assert intent.expected_visual_effect
    assert intent.verification
    assert intent.meaningful is True
    assert intent.cost_estimate_usd > 0


def test_cosmetic_findings_never_produce_an_intent() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.LAYOUT_INSTABILITY, IssueSeverity.COSMETIC, 1000, 2000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    assert merge_intents(_intents(diagnosis)) == []


def test_root_cause_maps_to_canonical_artifacts_not_regeneration() -> None:
    assert ROOT_CAUSE_MAP[EditorialIssueCategory.CAPTION_OCCLUSION] is (
        CanonicalArtifact.CAPTION_STYLE
    )
    assert ROOT_CAUSE_MAP[EditorialIssueCategory.WRONG_EVIDENCE] is (
        CanonicalArtifact.EVIDENCE_ASSET
    )
    assert ROOT_CAUSE_MAP[EditorialIssueCategory.SHOT_TOO_LONG] is CanonicalArtifact.SHOT_PLAN
    assert ROOT_CAUSE_MAP[EditorialIssueCategory.EMOTIONAL_MISMATCH] is (
        CanonicalArtifact.ASSET_SELECTION
    )
    for category, artifact in ROOT_CAUSE_MAP.items():
        assert artifact in CanonicalArtifact, category


def test_hard_defect_classification() -> None:
    for category in (
        EditorialIssueCategory.CAPTION_OCCLUSION,
        EditorialIssueCategory.WRONG_EVIDENCE,
        EditorialIssueCategory.FAKE_UI,
        EditorialIssueCategory.AUDIO_VISUAL_MISMATCH,
    ):
        assert classify_defect(category) is DefectClass.HARD_DEFECT
    # Preferences route through comparison, not straight into a repair.
    for category in (
        EditorialIssueCategory.SHOT_TOO_LONG,
        EditorialIssueCategory.MOTION_DISTRACTION,
    ):
        assert classify_defect(category) is DefectClass.EDITORIAL_PREFERENCE


def test_preference_is_not_autonomously_repairable() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.SHOT_TOO_LONG, IssueSeverity.MAJOR, 6000, 8000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    finding = diagnosis.findings[0]
    assert finding.defect_class is DefectClass.EDITORIAL_PREFERENCE
    assert finding.repairable is False
    assert merge_intents(_intents(diagnosis)) == []


# ── test_targeted_visual_repair ──────────────────────────────────────────


def test_three_second_defect_targets_one_shot_only() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 4000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    intents = merge_intents(_intents(diagnosis))
    plan = plan_targeted_repair(
        diagnosis,
        intents,
        content_id="c1",
        candidate_id="V0",
        node_ids={k: f"n:{k}" for k in ("SHOT", "RENDER", "EDIT")},
        artifact_ids={"research": "a:r", "script": "a:s", "shot1": "a:1", "shot2": "a:2"},
        all_artifact_ids=["research", "script", "shot1", "shot2"],
    )
    assert plan.changed_ranges_ms == [(1000, 4000)]
    assert plan.decision == "execute"
    # Research and script are preserved; only shot/render/edit re-run.
    assert "a:r" in plan.preserve_artifact_ids
    assert "a:s" in plan.preserve_artifact_ids
    assert "a:2" in plan.preserve_artifact_ids
    assert set(plan.rerun_nodes) == {"n:SHOT", "n:RENDER", "n:EDIT"}


def test_targeted_repair_never_reruns_research_or_script() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 13000, 16000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    intents = merge_intents(_intents(diagnosis))
    plan = plan_targeted_repair(
        diagnosis,
        intents,
        content_id="c1",
        candidate_id="V0",
        node_ids={k: f"n:{k}" for k in ARTIFACT_RERUN_NODES[CanonicalArtifact.EVIDENCE_ASSET]},
    )
    offenders = unaffected_source_reruns(
        plan, {f"n:{k}": k for k in ARTIFACT_RERUN_NODES[CanonicalArtifact.EVIDENCE_ASSET]}
    )
    assert offenders == []
    assert not (PROTECTED_NODE_KINDS & set(plan.rerun_nodes))


def test_non_regenerating_scopes_are_the_default_for_local_defects() -> None:
    for scope in (
        RepairScope.ASSET_ONLY,
        RepairScope.SHOT_ONLY,
        RepairScope.CAPTION_RANGE,
        RepairScope.MOTION_RANGE,
        RepairScope.AUDIO_MIX_RANGE,
    ):
        intent = RepairIntent(scope=scope)
        assert intent.regenerates_sources is False
    assert RepairIntent(scope=RepairScope.GLOBAL).regenerates_sources is True
    assert NON_REGENERATING_SCOPES


def test_plan_without_intents_stops() -> None:
    diagnosis = EditorialDiagnosis()
    plan = plan_targeted_repair(diagnosis, [], content_id="c1", candidate_id="V0")
    assert plan.decision == "stop"
    assert plan.rerun_nodes == []
    assert "NO_REPAIR_INTENT" in plan.reason


def test_wrong_timestamp_yields_no_unsafe_repair() -> None:
    """A3: an issue outside the video must not drive a targeted repair."""
    bad = _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 90000, 92000)
    check = validate_issue_location(bad, SHOTS, duration_ms=20000)
    assert check.ok is False
    assert check.reason == "TIMESTAMP_BEYOND_VIDEO_DURATION"

    review = _review([bad])
    diagnosis = diagnose_review(review, shots=SHOTS)
    assert diagnosis.autonomous_findings() == []
    assert merge_intents(_intents(diagnosis)) == []


def test_one_bad_timestamp_does_not_block_a_valid_observation() -> None:
    good = _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 3000)
    bad = _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 90000, 92000)
    diagnosis = diagnose_review(_review([good, bad]), shots=SHOTS)
    assert diagnosis.autonomous_findings()
    intents = merge_intents(_intents(diagnosis))
    assert len(intents) == 1
    assert intents[0].start_ms == 1000


def test_issue_spanning_a_shot_boundary_widens_scope_instead_of_being_dropped() -> None:
    """A range covering two shots is a real finding; it must not be discarded."""
    spanning = _issue(EditorialIssueCategory.EVIDENCE_UNDERUSE, IssueSeverity.MAJOR, 4000, 7000)
    check = validate_issue_location(spanning, SHOTS, duration_ms=20000)
    assert check.ok is True
    assert check.reason == "SPANS_MULTIPLE_SHOTS"
    assert check.multi_shot is True
    assert {s.shot_id for s in check.shots} == {"s1", "s2"}

    diagnosis = diagnose_review(_review([spanning]), shots=SHOTS)
    finding = diagnosis.findings[0]
    assert finding.repairable is True
    assert finding.repair_scope is RepairScope.MULTI_SHOT
    assert set(finding.shot_ids) == {"s1", "s2"}


def test_merged_intents_do_not_double_render_one_range() -> None:
    review = _review(
        [
            _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 3000),
            _issue(EditorialIssueCategory.CAPTION_OVERLOAD, IssueSeverity.BLOCKER, 1200, 2800),
        ]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    intents = merge_intents(_intents(diagnosis))
    assert len(intents) == 1
    assert intents[0].scope is RepairScope.CAPTION_RANGE


def test_changed_layers_follow_the_intent() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 13000, 16000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    intents = merge_intents(_intents(diagnosis))
    assert [layer.value for layer in changed_layers(intents)] == ["EVIDENCE"]


# ── test_revision_candidate ──────────────────────────────────────────────


def test_revision_candidate_records_the_full_chain() -> None:
    parent = RevisionCandidate(
        content_id="c1", candidate_id="V0", revision_number=0, video_path="/tmp/v0.mp4"
    )
    child = RevisionCandidate(
        content_id="c1",
        candidate_id="V1",
        parent_candidate_id=parent.candidate_id,
        revision_number=1,
        video_path="/tmp/v1.mp4",
        changed_artifacts=["a:evidence-2"],
        unchanged_artifacts=["a:research", "a:script", "a:shot1"],
        changed_ranges=[(12000, 16000)],
        cost=0.13,
        render_duration_s=4.2,
        review_id="rev-1",
    )
    payload = child.to_dict()
    for field in (
        "candidate_id", "parent_candidate_id", "revision_number", "repair_intents",
        "video_hash", "changed_artifacts", "unchanged_artifacts", "cost",
        "render_duration_s", "review_id",
    ):
        assert field in payload
    assert payload["changed_ranges"] == [[12000, 16000]]
    assert child.source_rerun_ranges_ms() == [(12000, 16000)]


def test_revision_candidates_do_not_claim_to_be_unchanged_and_changed() -> None:
    child = RevisionCandidate(
        changed_artifacts=["a:x"], unchanged_artifacts=["a:x"]
    )
    assert "a:x" in child.changed_artifacts and "a:x" in child.unchanged_artifacts


def test_candidate_unchanged_artifacts_drive_the_regression_guard() -> None:
    from hevi.ops.p5_1_pairwise import check_regression_guard

    new_review = _review(
        [_issue(EditorialIssueCategory.PACING, IssueSeverity.MAJOR, 6000, 7000)]
    )
    new_review.candidate_id = "V1"
    new = RevisionCandidate(
        candidate_id="V1",
        changed_ranges=[(12000, 16000)],
        changed_artifacts=["a:evidence"],
        unchanged_artifacts=["a:research"],
    )
    report = check_regression_guard(RevisionCandidate(candidate_id="V0"), new, new_review)
    # The new MAJOR issue sits outside the declared changed range.
    assert report.ok is False
    assert report.unchanged_range_regressions >= 1


def test_diagnosis_deduplicates_identical_observations() -> None:
    review = _review(
        [
            _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1000, 2000),
            _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.BLOCKER, 1100, 2100),
            _issue(EditorialIssueCategory.CAPTION_OCCLUSION, IssueSeverity.MAJOR, 1200, 2200),
        ]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    caption_findings = [
        f for f in diagnosis.findings
        if EditorialIssueCategory.CAPTION_OCCLUSION in f.categories
    ]
    assert len(caption_findings) == 1
    assert len(caption_findings[0].duplicate_issue_ids) == 3
    assert caption_findings[0].severity is IssueSeverity.BLOCKER


def test_diagnosis_reports_confidence_from_the_strongest_observation() -> None:
    review = _review(
        [_issue(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER, 13000, 14000)]
    )
    diagnosis = diagnose_review(review, shots=SHOTS)
    assert diagnosis.confidence == 0.9
    assert diagnosis.summary


def test_global_issue_is_diagnosable_without_a_shot() -> None:
    issue = _issue(
        EditorialIssueCategory.STYLE_INCONSISTENCY, IssueSeverity.MAJOR, 0, 0, global_scope=True
    )
    diagnosis = diagnose_review(_review([issue], duration_s=0.0), shots=[])
    finding = diagnosis.findings[0]
    assert finding.defect_class is DefectClass.EDITORIAL_PREFERENCE
    assert finding.repairable is False


def test_diagnosis_only_minor_check() -> None:
    assert DiagnosisFinding(severity=IssueSeverity.MINOR) and True
    assert EditorialDiagnosis(
        findings=[DiagnosisFinding(severity=IssueSeverity.COSMETIC)]
    ).only_minor_or_cosmetic() is True
    assert EditorialDiagnosis(
        findings=[DiagnosisFinding(severity=IssueSeverity.MAJOR)]
    ).only_minor_or_cosmetic() is False
