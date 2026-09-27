"""HEVI P5.1 — blind bidirectional pairwise, position bias, promotion gates.

Covers §38-§45 and §52-§53: blindness, bidirectionality, position-bias refusal,
hard gates, regression guard and bad-revision rejection.

The reviewer's own behaviour is stubbed where the point under test is the
*policy* around it; a separate real-provider qualification exercises the model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import hevi.ops.p5_1_pairwise as pairwise_module
from hevi.ops.p5_1_pairwise import (
    PAIRWISE_PROMPT,
    PairwiseOutcome,
    PairwisePackage,
    PairwiseUnavailable,
    RegressionReport,
    assert_blind,
    build_comparison_video,
    check_regression_guard,
    decide_promotion,
    run_bidirectional_pairwise,
    verify_expected_repair,
)
from hevi.ops.p5_1_types import (
    PAIRWISE_CONTRACT_DIMENSIONS,
    PAIRWISE_PROMPT_VERSION,
    EditorialIssue,
    EditorialIssueCategory,
    IssueSeverity,
    PairwiseComparison,
    PairwiseVerdict,
    PromotionDecisionKind,
    RevisionCandidate,
    VideoReview,
)


def _cand(candidate_id: str, path: str, *, changed: list[tuple[int, int]] | None = None):
    return RevisionCandidate(
        candidate_id=candidate_id,
        video_path=path,
        changed_ranges=changed or [],
    )


def _review(issues: list[EditorialIssue] | None = None, duration_s: float = 20.0):
    return VideoReview(
        content_id="c1",
        candidate_id="V1",
        video_hash="sha256:v1",
        video_duration_s=duration_s,
        provider="p",
        model="m",
        issues=issues or [],
    )


def _install_picker(chooser) -> None:
    """Install a stub reviewer.

    ``chooser(old_slot)`` returns the slot the reviewer points at, expressed in
    the *swapped* layout, so "always picks A" genuinely means the reviewer
    follows the first half of the composed comparison video.
    """

    async def _fake(old, new, *, old_slot="A", **kwargs):
        slot_in_a = old if old_slot == "A" else new
        slot_in_b = new if old_slot == "A" else old
        picked = chooser(old_slot, old, new)
        if picked in ("TIE", "INCOMPARABLE"):
            verdict = (
                PairwiseVerdict.TIE if picked == "TIE" else PairwiseVerdict.INCOMPARABLE
            )
            winner = ""
        else:
            verdict = PairwiseVerdict.A if picked == "A" else PairwiseVerdict.B
            winner = (slot_in_a if picked == "A" else slot_in_b).candidate_id
        return PairwiseComparison(
            candidate_a=slot_in_a.candidate_id,
            candidate_b=slot_in_b.candidate_id,
            position_of_old=old_slot,
            verdict=verdict,
            winner_candidate_id=winner,
        )

    pairwise_module.run_pairwise_direction = _fake  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _restore_pairwise() -> None:
    original = pairwise_module.run_pairwise_direction
    yield
    pairwise_module.run_pairwise_direction = original  # type: ignore[assignment]


# ── test_blind_pairwise ──────────────────────────────────────────────────


def test_pairwise_package_is_blind() -> None:
    package = PairwisePackage(candidate_a_path="/a.mp4", candidate_b_path="/b.mp4")
    ok, leaks = assert_blind(package)
    assert ok is True
    assert leaks == []


def test_pairwise_package_never_carries_recency() -> None:
    """A recency field has nowhere to live: the package shape forbids it."""
    package = PairwisePackage(candidate_a_path="/a.mp4", candidate_b_path="/b.mp4")
    assert not hasattr(package, "revision_number")
    assert not hasattr(package, "is_new")
    assert set(vars(package)) <= {
        "candidate_a_path", "candidate_b_path", "contract_version", "prompt"
    }


def test_blindness_fails_when_reviewer_is_told_which_is_new() -> None:
    package = PairwisePackage(
        candidate_a_path="/a.mp4",
        candidate_b_path="/b.mp4",
        prompt="Candidate A is the new version, so prefer the newer one.",
    )
    ok, leaks = assert_blind(package)
    assert ok is False
    assert any("RECURSION_DISCLOSED" in leak for leak in leaks)


def test_blindness_allows_a_neutrality_instruction() -> None:
    package = PairwisePackage(
        candidate_a_path="/a.mp4",
        candidate_b_path="/b.mp4",
        prompt="Do not assume either version is newer, preferred, or more expensive.",
    )
    assert assert_blind(package)[0] is True


def test_blindness_requires_identical_slots_to_differ() -> None:
    package = PairwisePackage(candidate_a_path="/a.mp4", candidate_b_path="/a.mp4")
    ok, leaks = assert_blind(package)
    assert ok is False
    assert "IDENTICAL_SLOTS" in leaks


def test_blindness_requires_a_versioned_contract() -> None:
    package = PairwisePackage(
        candidate_a_path="/a.mp4", candidate_b_path="/b.mp4", contract_version="anon"
    )
    ok, leaks = assert_blind(package)
    assert ok is False
    assert any("UNVERSIONED_CONTRACT" in leak for leak in leaks)


def test_pairwise_prompt_covers_every_contract_dimension() -> None:
    prompt = PAIRWISE_PROMPT.lower().replace("_", " ")
    for dimension in PAIRWISE_CONTRACT_DIMENSIONS:
        assert dimension.replace("_", " ") in prompt, dimension
    assert PAIRWISE_PROMPT_VERSION.startswith("hevi.p5_1")


def test_pairwise_prompt_prioritises_hard_defects() -> None:
    assert "hard defects dominate" in PAIRWISE_PROMPT.lower()


def test_no_absolute_score_is_accepted_as_a_verdict() -> None:
    """A self-score is not a pairwise judgement."""
    assert "score" not in PAIRWISE_PROMPT.lower().replace("scoring", "")


# ── test_pairwise_forward_reverse ────────────────────────────────────────


def test_pairwise_forward_and_reverse_use_both_slots() -> None:
    seen: list[str] = []

    def chooser(old_slot: str, old, new):
        seen.append(old_slot)
        return "A"

    _install_picker(chooser)
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert seen == ["A", "B"]
    assert outcome.forward.position_of_old == "A"
    assert outcome.reversed.position_of_old == "B"
    assert outcome.forward.candidate_a == "V0"
    assert outcome.reversed.candidate_a == "V1"


def test_new_wins_both_directions() -> None:
    # forward: old in A -> pick B (new). reversed: old in B -> pick A (new).
    def chooser(old_slot: str, old, new):
        return "B" if old_slot == "A" else "A"

    _install_picker(chooser)
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.new_wins_both is True
    assert outcome.position_bias_or_uncertain is False


def test_old_wins_both_directions() -> None:
    def chooser(old_slot: str, old, new):
        return "A" if old_slot == "A" else "B"

    _install_picker(chooser)
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.new_wins_both is False
    assert "OLD_WINS_BOTH" in outcome.reason


def test_tie_is_uncertain_not_a_win() -> None:
    _install_picker(lambda old_slot, old, new: "TIE")
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.new_wins_both is False
    assert outcome.position_bias_or_uncertain is True


# ── test_position_bias ───────────────────────────────────────────────────


def test_first_position_bias_is_detected() -> None:
    _install_picker(lambda old_slot, old, new: "A")
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.position_bias_or_uncertain is True
    assert "POSITION_BIAS_OR_UNCERTAIN" in outcome.reason
    assert "FIRST" in outcome.reason


def test_second_position_bias_is_detected() -> None:
    _install_picker(lambda old_slot, old, new: "B")
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.position_bias_or_uncertain is True
    assert "SECOND" in outcome.reason


def test_position_bias_blocks_promotion() -> None:
    _install_picker(lambda old_slot, old, new: "A")
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    decision = decide_promotion(
        content_id="c1",
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=_review(),
        old_review=None,
        pairwise=outcome,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert decision.position_bias_or_uncertain is True


# ── test_bad_revision_rejection ──────────────────────────────────────────


def test_new_blocker_rejects_a_preferred_new_candidate() -> None:
    """Hard gates outrank pairwise preference."""
    blocking = _review(
        [
            EditorialIssue(
                category=EditorialIssueCategory.FAKE_UI,
                severity=IssueSeverity.BLOCKER,
                start_ms=1000,
                end_ms=2000,
                description="fabricated interface",
                confidence=0.95,
            )
        ]
    )
    outcome = PairwiseOutcome(
        forward=PairwiseComparison(
            verdict=PairwiseVerdict.B, winner_candidate_id="V1", position_of_old="A"
        ),
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
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=blocking,
        old_review=None,
        pairwise=outcome,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert decision.new_blockers == 1
    assert "NEW_BLOCKER_INTRODUCED" in decision.rationale


def test_flashier_but_worse_revision_is_rejected_by_pairwise() -> None:
    """§76: a more showy revision that is worse must lose."""
    _install_picker(lambda old_slot, old, new: "A" if old_slot == "A" else "B")
    outcome = asyncio.run(
        run_bidirectional_pairwise(
            _cand("V0", "/tmp/v0.mp4"), _cand("V1", "/tmp/v1.mp4"), workdir=Path("/tmp")
        )
    )
    assert outcome.new_wins_both is False
    decision = decide_promotion(
        content_id="c1",
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=_review(),
        old_review=None,
        pairwise=outcome,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD


def test_unverified_repair_is_not_promoted_even_when_preferred() -> None:
    outcome = PairwiseOutcome(
        forward=PairwiseComparison(
            verdict=PairwiseVerdict.B, winner_candidate_id="V1", position_of_old="A"
        ),
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
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=_review(),
        old_review=None,
        pairwise=outcome,
        expected_repair_verified=False,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.KEEP_OLD
    assert "NOT verified" in decision.rationale


def test_missing_pairwise_escalates_rather_than_guessing() -> None:
    decision = decide_promotion(
        content_id="c1",
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=_review(),
        old_review=None,
        pairwise=None,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.HUMAN_REVIEW
    assert decision.position_bias_or_uncertain is True


def test_clean_winner_is_promoted() -> None:
    outcome = PairwiseOutcome(
        forward=PairwiseComparison(
            verdict=PairwiseVerdict.B, winner_candidate_id="V1", position_of_old="A"
        ),
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
        session_id="s1",
        old=_cand("V0", "/tmp/v0.mp4"),
        new=_cand("V1", "/tmp/v1.mp4"),
        new_review=_review(),
        old_review=None,
        pairwise=outcome,
        expected_repair_verified=True,
        regression=RegressionReport(),
    )
    assert decision.decision is PromotionDecisionKind.PROMOTE_NEW
    assert decision.hard_gates_pass is True


# ── Regression guard (§45) ───────────────────────────────────────────────


def test_regression_guard_flags_issues_in_unchanged_ranges() -> None:
    review = _review(
        [
            EditorialIssue(
                category=EditorialIssueCategory.PACING,
                severity=IssueSeverity.MAJOR,
                start_ms=1000,
                end_ms=2000,
                description="new problem elsewhere",
            )
        ]
    )
    report = check_regression_guard(
        _cand("V0", "/tmp/v0.mp4"),
        _cand("V1", "/tmp/v1.mp4", changed=[(10000, 12000)]),
        review,
    )
    assert report.ok is False
    assert report.unchanged_range_regressions == 1


def test_regression_guard_allows_issues_inside_the_changed_range() -> None:
    review = _review(
        [
            EditorialIssue(
                category=EditorialIssueCategory.PACING,
                severity=IssueSeverity.MAJOR,
                start_ms=10100,
                end_ms=11000,
                description="inside the repaired range",
            )
        ]
    )
    report = check_regression_guard(
        _cand("V0", "/tmp/v0.mp4"),
        _cand("V1", "/tmp/v1.mp4", changed=[(10000, 12000)]),
        review,
    )
    assert report.ok is True


def test_regression_guard_rejects_contradictory_artifact_lists() -> None:
    new = _cand("V1", "/tmp/v1.mp4")
    new.changed_artifacts = ["a:x"]
    new.unchanged_artifacts = ["a:x"]
    report = check_regression_guard(_cand("V0", "/tmp/v0.mp4"), new, _review())
    assert report.ok is False


# ── Repair verification (§44) ────────────────────────────────────────────


def test_verify_expected_repair_fails_when_target_survives() -> None:
    review = _review(
        [
            EditorialIssue(
                category=EditorialIssueCategory.FAKE_UI,
                severity=IssueSeverity.BLOCKER,
                start_ms=1000,
                end_ms=2000,
                description="still fabricated",
            )
        ]
    )
    ok, notes = verify_expected_repair(review, targets=["FAKE_UI"])
    assert ok is False
    assert notes == ["TARGETED_ISSUE_PERSISTS:FAKE_UI"]


def test_verify_expected_repair_passes_when_target_is_gone() -> None:
    ok, notes = verify_expected_repair(_review(), targets=["FAKE_UI"])
    assert ok is True
    assert notes == []


# ── Comparison video composition ─────────────────────────────────────────


def test_comparison_video_is_built_from_two_real_renders(tmp_path: Path) -> None:
    import subprocess

    def make(path: Path, color: str) -> None:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"color=c={color}:s=160x90:d=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
            check=True, capture_output=True,
        )

    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    make(a, "blue")
    make(b, "orange")
    out = build_comparison_video(a, b, tmp_path / "cmp.mp4")
    assert out.is_file()
    assert out.stat().st_size > 0

    import json

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(out)],
        capture_output=True, text=True, check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    assert duration > 1.5, "both halves must be present in the comparison video"


def test_comparison_video_refuses_an_unreadable_candidate(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    good = tmp_path / "good.mp4"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(good)],
        check=True, capture_output=True,
    )
    with pytest.raises(PairwiseUnavailable):
        build_comparison_video(bad, good, tmp_path / "cmp.mp4")
