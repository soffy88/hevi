"""HEVI P5.1 — no-progress detection, revision budget, human override.

Covers §35-§37 and §46-§48 plus §67: convergence limits, stop conditions and the
human override that outranks autonomous promotion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.ops.p5_1_session import (
    NO_PROGRESS_CATEGORY_STREAK,
    apply_human_decision,
    check_meaningful_revision,
    detect_no_progress,
    evaluate_stop_conditions,
    new_session,
)
from hevi.ops.p5_1_types import (
    MAX_REVISION_ROUNDS,
    CanonicalArtifact,
    DiagnosisFinding,
    EditorialDiagnosis,
    EditorialIssueCategory,
    HumanDecision,
    IssueSeverity,
    PromotionDecision,
    PromotionDecisionKind,
    RepairIntent,
    RepairScope,
    RevisionCandidate,
    RevisionSession,
    SessionCost,
    SessionStopReason,
)


def _finding(
    category: EditorialIssueCategory,
    severity: IssueSeverity,
    *,
    repairable: bool = True,
    artifact: CanonicalArtifact = CanonicalArtifact.EVIDENCE_ASSET,
    scope: RepairScope = RepairScope.ASSET_ONLY,
) -> DiagnosisFinding:
    return DiagnosisFinding(
        categories=[category],
        severity=severity,
        repairable=repairable,
        canonical_artifact=artifact,
        repair_scope=scope,
    )


def _intent(*, meaningful: bool, scope: RepairScope = RepairScope.ASSET_ONLY) -> RepairIntent:
    return RepairIntent(
        diagnosis_id="d1",
        target_artifacts=[CanonicalArtifact.EVIDENCE_ASSET],
        expected_change="bind real evidence",
        expected_visual_effect="claim is grounded",
        verification="re-review the range",
        scope=scope,
        meaningful=meaningful,
    )


def _session_with(chain: list[list[EditorialIssueCategory]]) -> RevisionSession:
    session = new_session("c1", "KNOWLEDGE_TALK_FINECUT")
    for index, categories in enumerate(chain):
        candidate_id = f"V{index}"
        session.candidates.append(
            RevisionCandidate(
                content_id="c1",
                candidate_id=candidate_id,
                revision_number=index,
                video_path=f"/tmp/{candidate_id}.mp4",
            )
        )
        session.diagnoses[candidate_id] = EditorialDiagnosis(
            findings=[
                _finding(category, IssueSeverity.MAJOR) for category in categories
            ]
        )
    return session


# ── Revision budget (§36, §46) ───────────────────────────────────────────


def test_max_revision_rounds_is_three() -> None:
    assert MAX_REVISION_ROUNDS == 3
    assert new_session("c1").max_revision_rounds == 3


def test_revision_budget_decreases_per_round() -> None:
    """V0 is the original; each later candidate consumes one revision round."""
    session = new_session("c1")
    assert session.rounds_remaining() == 3
    for index in range(3):
        session.add_candidate(
            RevisionCandidate(candidate_id=f"V{index}", revision_number=index, video_path="/x")
        )
    assert session.revision_count == 2
    assert session.rounds_remaining() == 1


def test_revision_budget_exhausted_stops_cleanly() -> None:
    # Distinct categories each round, so only the budget can be the reason.
    session = _session_with(
        [
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.PACING],
            [EditorialIssueCategory.SUBJECT_JUMP],
            [EditorialIssueCategory.DEAD_AIR],
        ]
    )
    session.max_revision_rounds = 0
    diagnosis = session.diagnoses["V3"]
    stop = evaluate_stop_conditions(session, diagnosis, None)
    assert stop is SessionStopReason.MAX_REVISION_ROUNDS_REACHED


def test_editorial_budget_does_not_leak_into_mission_termination() -> None:
    """The editorial budget belongs to P5.1 only.

    The P3 mission runtime must not learn about the editorial revision budget,
    otherwise the editorial loop would be silently re-deriving a mission-level
    round limit.
    """
    root = Path(__file__).resolve().parents[1] / "hevi"
    session = new_session("c1")
    assert session.max_revision_rounds == 3
    for module in (root / "missions").rglob("*.py"):
        assert "max_revision_rounds" not in module.read_text(encoding="utf-8"), module


def test_budget_exhaustion_stops() -> None:
    session = new_session("c1", budget_usd=0.5)
    session.cost = SessionCost(review_cost_usd=0.6)
    diagnosis = EditorialDiagnosis(
        findings=[_finding(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER)]
    )
    assert evaluate_stop_conditions(session, diagnosis, None) is (
        SessionStopReason.BUDGET_EXHAUSTED
    )


def test_budget_headroom_is_reported() -> None:
    session = new_session("c1", budget_usd=1.0)
    session.cost.review_cost_usd = 0.25
    assert session.budget_remaining_usd() == 0.75


# ── Stop conditions (§46) ────────────────────────────────────────────────


def test_stop_when_no_blocker_or_major_issues() -> None:
    session = new_session("c1")
    assert evaluate_stop_conditions(session, EditorialDiagnosis(), None) is (
        SessionStopReason.NO_BLOCKER_OR_MAJOR_ISSUES
    )


def test_stop_when_only_minor_or_cosmetic_remains() -> None:
    session = new_session("c1")
    diagnosis = EditorialDiagnosis(
        findings=[
            _finding(EditorialIssueCategory.PACING, IssueSeverity.COSMETIC, repairable=False)
        ]
    )
    assert evaluate_stop_conditions(session, diagnosis, None) is (
        SessionStopReason.ONLY_MINOR_COSMETIC_REMAINS
    )


def test_stop_when_new_candidate_was_not_promoted() -> None:
    session = new_session("c1")
    diagnosis = EditorialDiagnosis(
        findings=[_finding(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER)]
    )
    promotion = PromotionDecision(decision=PromotionDecisionKind.KEEP_OLD)
    assert evaluate_stop_conditions(session, diagnosis, promotion) is (
        SessionStopReason.NEW_NOT_PROMOTED
    )


def test_stop_on_human_review_required() -> None:
    session = new_session("c1")
    diagnosis = EditorialDiagnosis(
        findings=[_finding(EditorialIssueCategory.FAKE_UI, IssueSeverity.BLOCKER)]
    )
    promotion = PromotionDecision(decision=PromotionDecisionKind.HUMAN_REVIEW)
    assert evaluate_stop_conditions(session, diagnosis, promotion) is (
        SessionStopReason.HUMAN_REVIEW_REQUIRED
    )


def test_stop_when_provider_unavailable() -> None:
    session = new_session("c1")
    session.provider_available = False
    assert evaluate_stop_conditions(session, EditorialDiagnosis(), None) is (
        SessionStopReason.PROVIDER_UNAVAILABLE
    )


def test_session_stop_is_recorded_once() -> None:
    session = new_session("c1")
    session.stop(SessionStopReason.BUDGET_EXHAUSTED)
    session.stop(SessionStopReason.NO_PROGRESS_DETECTED)
    assert session.stop_reason is SessionStopReason.BUDGET_EXHAUSTED
    assert session.is_stopped()


# ── Meaningful revision (§37) ────────────────────────────────────────────


def test_revision_without_intents_is_refused() -> None:
    verdict = check_meaningful_revision([], EditorialDiagnosis())
    assert verdict.ok is False
    assert "NO_REPAIR_INTENT" in verdict.reason


def test_major_or_blocker_repair_makes_a_meaningful_revision() -> None:
    verdict = check_meaningful_revision([_intent(meaningful=True)], EditorialDiagnosis())
    assert verdict.ok is True
    assert verdict.driving_intents


def test_cosmetic_only_revision_is_refused() -> None:
    verdict = check_meaningful_revision([_intent(meaningful=False)], EditorialDiagnosis())
    assert verdict.ok is False
    assert "MEANINGFUL_REVISION_REFUSED" in verdict.reason


def test_declared_hypothesis_makes_a_minor_revision_meaningful() -> None:
    verdict = check_meaningful_revision(
        [_intent(meaningful=False)],
        EditorialDiagnosis(),
        hypothesis="tighten the caption safe area by 8% so the subject clears the text",
    )
    assert verdict.ok is True
    assert "hypothesis" in verdict.reason


def test_hypothesis_without_a_targeted_intent_is_not_enough() -> None:
    verdict = check_meaningful_revision(
        [], EditorialDiagnosis(), hypothesis="make it nicer somehow"
    )
    assert verdict.ok is False


# ── test_no_progress ─────────────────────────────────────────────────────


def test_no_progress_detected_when_same_category_persists() -> None:
    session = _session_with(
        [
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.FAKE_UI],
        ]
    )
    detected, reason = detect_no_progress(session)
    assert detected is True
    assert "NO_PROGRESS_DETECTED" in reason
    assert "FAKE_UI" in reason


def test_no_progress_not_detected_when_issues_change() -> None:
    session = _session_with(
        [
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.PACING],
            [EditorialIssueCategory.CAPTION_OCCLUSION],
        ]
    )
    assert detect_no_progress(session) == (False, "")


def test_no_progress_streak_threshold() -> None:
    session = _session_with(
        [
            [EditorialIssueCategory.PACING],
            [EditorialIssueCategory.PACING, EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.PACING, EditorialIssueCategory.FAKE_UI],
        ]
    )
    detected, _ = detect_no_progress(session)
    assert detected is True
    assert session.no_progress_streak >= NO_PROGRESS_CATEGORY_STREAK


def test_single_revision_never_reports_no_progress() -> None:
    session = _session_with([[EditorialIssueCategory.FAKE_UI]])
    assert detect_no_progress(session) == (False, "")


def test_no_progress_blocks_further_autonomy() -> None:
    session = _session_with(
        [
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.FAKE_UI],
            [EditorialIssueCategory.FAKE_UI],
        ]
    )
    diagnosis = session.diagnoses["V2"]
    assert evaluate_stop_conditions(session, diagnosis, None) is (
        SessionStopReason.NO_PROGRESS_DETECTED
    )


# ── test_human_override (§67) ────────────────────────────────────────────


def _two_candidate_session() -> RevisionSession:
    session = new_session("c1", "KNOWLEDGE_TALK_FINECUT")
    session.candidates = [
        RevisionCandidate(
            content_id="c1", candidate_id="V0", revision_number=0, video_path="/tmp/v0.mp4"
        ),
        RevisionCandidate(
            content_id="c1", candidate_id="V1", revision_number=1, video_path="/tmp/v1.mp4"
        ),
    ]
    return session


def test_human_override_keeping_v0_makes_v0_authoritative() -> None:
    session = _two_candidate_session()
    promotion = apply_human_decision(session, HumanDecision.KEEP_V0)
    assert promotion.decision is PromotionDecisionKind.KEEP_OLD
    assert session.authoritative_candidate_id == "V0"
    assert promotion.human_override is HumanDecision.KEEP_V0


def test_human_override_keeping_v1_makes_v1_authoritative() -> None:
    session = _two_candidate_session()
    promotion = apply_human_decision(session, HumanDecision.KEEP_V1)
    assert promotion.decision is PromotionDecisionKind.PROMOTE_NEW
    assert session.authoritative_candidate_id == "V1"


def test_human_reject_all_stops_the_session() -> None:
    session = _two_candidate_session()
    promotion = apply_human_decision(session, HumanDecision.REJECT_ALL)
    assert promotion.decision is PromotionDecisionKind.HUMAN_REVIEW
    assert session.stop_reason is SessionStopReason.HUMAN_REVIEW_REQUIRED


def test_human_request_change_asks_for_another_pass() -> None:
    session = _two_candidate_session()
    promotion = apply_human_decision(session, HumanDecision.REQUEST_CHANGE)
    assert promotion.decision is PromotionDecisionKind.HUMAN_REVIEW
    assert "REQUEST_CHANGE" in promotion.rationale


def test_human_override_outranks_a_clean_pairwise_win() -> None:
    """Even a clean bidirectional win cannot overrule a human."""
    session = _two_candidate_session()
    session.authoritative_candidate_id = "V1"
    promotion = apply_human_decision(session, HumanDecision.KEEP_V0)
    assert promotion.decision is PromotionDecisionKind.KEEP_OLD
    assert session.authoritative_candidate_id == "V0"
    assert "HUMAN_OVERRIDE" in promotion.rationale


def test_human_decision_provenance_is_recorded() -> None:
    session = _two_candidate_session()
    apply_human_decision(session, HumanDecision.KEEP_V1)
    assert session.human_decision is HumanDecision.KEEP_V1
    payload = session.to_dict()
    assert payload["human_decision"] == "KEEP_V1"
    assert payload["promotions"][0]["human_override"] == "KEEP_V1"


# ── Cost accounting (§48, §81) ───────────────────────────────────────────


def test_cost_keeps_unknown_items_distinct_from_zero() -> None:
    from hevi.ops.p5_1_pairwise import PairwiseOutcome
    from hevi.ops.p5_1_session import add_pairwise_cost, add_review_cost
    from hevi.ops.p5_1_types import PairwiseComparison, VideoReview

    session = new_session("c1", budget_usd=5.0)
    add_review_cost(session, VideoReview(cost_usd=None))
    assert session.cost.review_cost_usd == 0.0
    assert session.cost.unknown_cost_items == 1

    add_pairwise_cost(
        session,
        PairwiseOutcome(
            forward=PairwiseComparison(cost_usd=None),
            reversed=PairwiseComparison(cost_usd=0.02),
            old_wins_forward=False,
            old_wins_reversed=False,
        ),
    )
    assert session.cost.pairwise_cost_usd == 0.02
    assert session.cost.unknown_cost_items == 2
    assert session.cost.known_total_usd == 0.02


def test_session_counters_reflect_promotion_outcomes() -> None:
    session = _two_candidate_session()
    session.record_promotion(
        PromotionDecision(decision=PromotionDecisionKind.PROMOTE_NEW)
    )
    session.record_promotion(PromotionDecision(decision=PromotionDecisionKind.KEEP_OLD))
    session.record_promotion(PromotionDecision(decision=PromotionDecisionKind.HUMAN_REVIEW))
    assert session.promoted_count() == 1
    assert session.rejected_count() == 1
    assert session.uncertain_count() == 1


def test_session_serialises_full_lineage() -> None:
    session = _two_candidate_session()
    payload = session.to_dict()
    for key in (
        "session_id", "content_id", "candidates", "reviews", "diagnoses",
        "pairwise", "promotions", "cost", "stop_reason", "authoritative_candidate_id",
    ):
        assert key in payload


@pytest.mark.parametrize(
    "decision", [HumanDecision.KEEP_V0, HumanDecision.KEEP_V1, HumanDecision.REJECT_ALL]
)
def test_every_human_decision_is_recorded(decision: HumanDecision) -> None:
    session = _two_candidate_session()
    promotion = apply_human_decision(session, decision)
    assert promotion.human_override is decision
