"""HEVI P5.1 — reviewer calibration and qualification.

Covers §49-§53: the known-pair calibration set, accuracy, position-swap
consistency, and the rule that a reviewer which cannot be trusted must not be
allowed to promote candidates autonomously.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import hevi.ops.p5_1_pairwise as pairwise_module
from hevi.ops.p5_1_calibration import (
    MIN_ACCURACY,
    MIN_KNOWN_PAIRS,
    MIN_POSITION_SWAP_CONSISTENCY,
    CalibrationPair,
    CalibrationReport,
    CalibrationResult,
    build_calibration_set,
    calibration_fingerprint,
    qualification_verdict,
    run_calibration,
)
from hevi.ops.p5_1_pairwise import PairwiseComparison
from hevi.ops.p5_1_types import (
    PAIRWISE_PROMPT_VERSION,
    REVIEW_PROMPT_VERSION,
    PairwiseVerdict,
)

# ── Prompt / contract versioning (§49) ───────────────────────────────────


def test_reviewer_contracts_are_versioned() -> None:
    assert REVIEW_PROMPT_VERSION.startswith("hevi.p5_1")
    assert PAIRWISE_PROMPT_VERSION.startswith("hevi.p5_1")
    assert REVIEW_PROMPT_VERSION != PAIRWISE_PROMPT_VERSION


# ── Calibration set (§50) ────────────────────────────────────────────────


@pytest.mark.slow
def test_calibration_set_has_at_least_ten_known_pairs(tmp_path: Path) -> None:
    pairs = build_calibration_set(tmp_path)
    assert len(pairs) >= MIN_KNOWN_PAIRS
    for pair in pairs:
        assert Path(pair.better_path).is_file()
        assert Path(pair.worse_path).is_file()
        assert Path(pair.better_path).read_bytes() != Path(pair.worse_path).read_bytes()


@pytest.mark.slow
def test_calibration_set_covers_hard_defects_and_flashiness(tmp_path: Path) -> None:
    defects = {pair.defect for pair in build_calibration_set(tmp_path)}
    assert "DEAD_BLACK_STRETCH" in defects
    assert "EXCESSIVE_MOTION" in defects


def test_calibration_fingerprint_is_stable() -> None:
    pairs = [
        CalibrationPair(pair_id="P1", better_path="/a/x.mp4", worse_path="/a/y.mp4", defect="D"),
        CalibrationPair(pair_id="P2", better_path="/a/z.mp4", worse_path="/a/w.mp4", defect="E"),
    ]
    assert calibration_fingerprint(pairs) == calibration_fingerprint(pairs)
    assert calibration_fingerprint(pairs) != calibration_fingerprint(pairs[:1])


# ── Qualification thresholds (§51, §94) ──────────────────────────────────


def _report(**overrides) -> CalibrationReport:
    base = {
        "pair_count": 12,
        "correct": 12,
        "accuracy": 1.0,
        "position_swaps_consistent": 12,
        "position_swap_consistency": 1.0,
        "hard_defect_detection": 1.0,
    }
    base.update(overrides)
    return CalibrationReport(**base)


def test_thresholds_match_the_specification() -> None:
    assert MIN_KNOWN_PAIRS == 10
    assert MIN_ACCURACY == 0.80
    assert MIN_POSITION_SWAP_CONSISTENCY == 0.90


def test_a_clean_reviewer_qualifies() -> None:
    report = _report()
    assert report.qualified is True
    assert qualification_verdict(report) == "QUALIFIED"


def test_accuracy_below_threshold_disqualifies() -> None:
    report = _report(accuracy=0.5)
    assert report.qualified is False
    assert any("CALIBRATION_ACCURACY" in reason for reason in report.failure_reasons)
    assert qualification_verdict(report) == "NOT_QUALIFIED"


def test_position_swap_consistency_below_threshold_disqualifies() -> None:
    report = _report(position_swap_consistency=0.6)
    assert report.qualified is False
    assert any("POSITION_SWAP_CONSISTENCY" in reason for reason in report.failure_reasons)


def test_too_few_pairs_disqualifies() -> None:
    report = _report(pair_count=4, accuracy=1.0, position_swap_consistency=1.0)
    assert report.qualified is False
    assert any("KNOWN_PAIR_COUNT" in reason for reason in report.failure_reasons)


def test_flashiness_preference_disqualifies() -> None:
    report = _report(flashiness_preference=True)
    assert report.qualified is False
    assert "PREFERS_FLASHIER_OVER_BETTER" in report.failure_reasons


def test_newer_default_bias_disqualifies() -> None:
    report = _report(newer_default_bias=True)
    assert report.qualified is False
    assert "DEFAULTS_TO_NEWER_CANDIDATE" in report.failure_reasons


def test_no_pairs_is_not_qualified() -> None:
    report = CalibrationReport()
    assert report.qualified is False
    assert qualification_verdict(report) == "NOT_QUALIFIED"


# ── Runner behaviour against a stub reviewer ─────────────────────────────


@pytest.fixture(autouse=True)
def _restore_pairwise() -> None:
    original = pairwise_module.run_pairwise_direction
    yield
    pairwise_module.run_pairwise_direction = original  # type: ignore[attr-defined]


def _install(always_pick: str) -> None:
    """Install a stub reviewer.

    ``always_pick`` is a slot (``"A"``/``"B"``) or the sentinel ``"CONTENT"``,
    which makes the reviewer follow the *better* clip wherever it sits. The
    distinction is the whole point: a content-following reviewer is
    position-stable, a slot-following one is not.
    """

    async def _fake(old, new, *, old_slot="A", **kwargs):
        slot_in_a = old if old_slot == "A" else new
        slot_in_b = new if old_slot == "A" else old
        if always_pick == "CONTENT":
            picked = "A" if slot_in_a.candidate_id == old.candidate_id else "B"
        else:
            picked = always_pick
        winner = (slot_in_a if picked == "A" else slot_in_b).candidate_id
        return PairwiseComparison(
            candidate_a=slot_in_a.candidate_id,
            candidate_b=slot_in_b.candidate_id,
            position_of_old=old_slot,
            verdict=PairwiseVerdict.A if picked == "A" else PairwiseVerdict.B,
            winner_candidate_id=winner,
        )

    pairwise_module.run_pairwise_direction = _fake  # type: ignore[assignment]


def _pairs(tmp_path: Path) -> list[CalibrationPair]:
    """Pair list whose 'better' is always in the first position when paired."""
    return [
        CalibrationPair(
            pair_id=f"P{i}",
            better_path=str(tmp_path / f"p{i}_better.mp4"),
            worse_path=str(tmp_path / f"p{i}_worse.mp4"),
            defect="DEAD_BLACK_STRETCH" if i < 4 else "EXCESSIVE_MOTION",
        )
        for i in range(10)
    ]


def test_perfect_reviewer_scores_full_marks(tmp_path: Path) -> None:
    _install("CONTENT")  # follows the better clip wherever it sits
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    assert report.pair_count == 10
    assert report.accuracy == 1.0
    assert report.position_swap_consistency == 1.0
    assert report.qualified is True


def test_position_biased_reviewer_fails_position_swap(tmp_path: Path) -> None:
    """A reviewer that always points at slot A is not position-stable.

    In this calibration set the *worse* clip is placed second, so an
    always-slot-A reviewer wins forward and loses reversed.
    """
    _install("A")
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    assert report.position_swap_consistency < MIN_POSITION_SWAP_CONSISTENCY
    assert report.qualified is False
    assert any("POSITION_SWAP_CONSISTENCY" in r for r in report.failure_reasons)


def test_prefers_the_worse_clip_is_measured(tmp_path: Path) -> None:
    _install("B")
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    assert report.accuracy == 0.0
    assert report.qualified is False


def test_unavailable_reviewer_does_not_inflate_the_score(tmp_path: Path) -> None:
    async def _boom(*args, **kwargs):
        from hevi.ops.p5_1_pairwise import PairwiseUnavailable

        raise PairwiseUnavailable("BLOCKED_BY_PROVIDER")

    pairwise_module.run_pairwise_direction = _boom  # type: ignore[assignment]
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    assert report.correct == 0
    assert report.accuracy == 0.0
    assert report.qualified is False
    assert all("UNAVAILABLE" in r.note for r in report.results)


def test_calibration_result_records_both_directions(tmp_path: Path) -> None:
    _install("CONTENT")
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    for result in report.results:
        assert result.forward_picked
        assert result.reversed_picked
        assert isinstance(result, CalibrationResult)


def test_calibration_serialises_for_the_qualification_record(tmp_path: Path) -> None:
    _install("CONTENT")
    pairs = _pairs(tmp_path)
    for pair in pairs:
        Path(pair.better_path).write_bytes(b"better")
        Path(pair.worse_path).write_bytes(b"worse")
    report = asyncio.run(run_calibration(pairs, workdir=tmp_path / "run"))
    payload = report.to_dict()
    for key in (
        "pair_count", "accuracy", "position_swap_consistency", "hard_defect_detection",
        "flashiness_preference", "newer_default_bias", "qualified", "failure_reasons",
        "results",
    ):
        assert key in payload
