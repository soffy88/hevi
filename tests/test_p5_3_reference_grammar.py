"""HEVI P5.3 — reference grammar tests: VIDEO -> ABSTRACT GRAMMAR, not copy."""

from __future__ import annotations

from hevi.production.p5_3.reference_grammar import ReferenceVideoAnalysis


def test_analysis_produces_grammar() -> None:
    a = ReferenceVideoAnalysis(
        "ref1", duration_s=30, shot_count=5,
        shot_durations=[1.5, 2.0, 3.0, 4.0, 8.0],
        composition_labels=["centered", "split"],
        camera_labels=["push_in", "pan"],
        transition_labels=["fade", "cut"],
        motion_labels=["static", "push_in"],
    )
    g = a.to_grammar()
    assert g.reference_id == "ref1"
    assert g.pacing_signature == "mixed_pacing"
    assert "centered" in g.composition_families
    assert "push_in" in g.camera_families


def test_grammar_has_no_ordered_sequences() -> None:
    """ReferenceGrammar must not contain ordered shot sequences."""
    a = ReferenceVideoAnalysis(
        "ref1", duration_s=30, shot_count=3,
        shot_durations=[2.0, 3.0, 4.0],
        composition_labels=["centered"], camera_labels=["push_in"],
        transition_labels=["fade"], motion_labels=["static"],
    )
    g = a.to_grammar()
    # No ordered sequence fields
    assert not hasattr(g, "shot_sequence")
    assert not hasattr(g, "timing_vector")
    assert not hasattr(g, "asset_sequence")


def test_pacing_signature_fast() -> None:
    a = ReferenceVideoAnalysis("ref1", shot_durations=[0.5, 1.0, 1.5])
    assert a.to_grammar().pacing_signature == "fast_cut"


def test_pacing_signature_slow() -> None:
    a = ReferenceVideoAnalysis("ref1", shot_durations=[7.0, 8.0, 9.0])
    assert a.to_grammar().pacing_signature == "slow_hold"


def test_duration_distribution() -> None:
    a = ReferenceVideoAnalysis("ref1", shot_durations=[1.0, 3.0, 7.0])
    dist = a.to_grammar().shot_duration_distribution
    assert dist["fast"] > 0
    assert dist["medium"] > 0
    assert dist["slow"] > 0


def test_speaker_evidence_pattern() -> None:
    a = ReferenceVideoAnalysis(
        "ref1", speaker_segments=[{}], evidence_segments=[{}],
    )
    assert a.to_grammar().speaker_evidence_pattern == "speaker_with_evidence"


def test_narrative_arc_steady() -> None:
    a = ReferenceVideoAnalysis("ref1", shot_durations=[3.0, 3.0, 3.0])
    assert a.to_grammar().narrative_arc == "steady"


def test_information_density_curve() -> None:
    a = ReferenceVideoAnalysis("ref1", shot_durations=[2.0, 4.0])
    curve = a.to_grammar().information_density_curve
    assert len(curve) == 2
    assert all(0.0 <= v <= 1.0 for v in curve)
