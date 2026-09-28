import pytest
from hevi.production.p5_3_corpus import (
    VideoAgentReferenceCorpus,
    ReferenceRepository,
    AdoptionMode
)
from hevi.production.p5_3_reference import (
    ReferenceGrammar,
    AntiCopyGuard,
    P5_3_Gates
)

def test_reference_corpus_loading():
    corpus = VideoAgentReferenceCorpus("data/p5_3_reference_corpus.json")
    entries = corpus.list_entries()
    assert len(entries) >= 12
    
    # Check specific entries
    om = corpus.get_entry("OpenMontage")
    assert om is not None
    assert om.adoption_mode == AdoptionMode.REFERENCE_ONLY
    
    hf = corpus.get_entry("HyperFrames")
    assert hf is not None

def test_repository_gates():
    corpus = VideoAgentReferenceCorpus("data/p5_3_reference_corpus.json")
    repo = ReferenceRepository(corpus)
    
    assert repo.allow_code_execution("OpenMontage") is False
    assert repo.allow_unlicensed_import() is False
    assert repo.check_license_boundary("OpenMontage") is True

def test_anti_copy_guards():
    # Ordered shot sequence
    source_shots = ["wide", "medium", "close", "extreme_close"]
    target_shots_1 = ["wide", "medium", "close", "wide"] # copy of 3
    target_shots_2 = ["wide", "close", "medium", "wide"] # no copy
    
    assert AntiCopyGuard.check_ordered_shot_sequence(source_shots, target_shots_1) is False
    assert AntiCopyGuard.check_ordered_shot_sequence(source_shots, target_shots_2) is True
    
    # Timing vector
    source_timings = [1.0, 2.0, 3.0]
    target_timings_1 = [1.05, 2.05, 3.05]
    target_timings_2 = [1.5, 2.5, 3.5]
    
    assert AntiCopyGuard.check_timing_vector(source_timings, target_timings_1) is False
    assert AntiCopyGuard.check_timing_vector(source_timings, target_timings_2) is True

def test_reference_grammar():
    grammar = ReferenceGrammar(
        pacing_distribution={"fast": 0.3, "medium": 0.5, "slow": 0.2},
        composition_families=["rule_of_thirds", "centered"],
        camera_families=["static", "pan"],
        transition_families=["cut", "fade"],
        speaker_pattern="interleaved",
        evidence_pattern="b-roll_overlay",
        information_density=0.8,
        narrative_arc="problem_solution",
        caption_behavior="dynamic_pop",
        audio_visual_behavior="beat_sync"
    )
    assert grammar.pacing_distribution["fast"] == 0.3

def test_gates_constants():
    assert P5_3_Gates.REFERENCE_CORPUS is True
    assert P5_3_Gates.REFERENCE_GRAMMAR is True
    assert P5_3_Gates.REFERENCE_ABSTRACTION is True
    assert P5_3_Gates.REFERENCE_VIDEO_COPYING == 0
    assert P5_3_Gates.RECIPE_PROVENANCE is True
    assert P5_3_Gates.LICENSE_BOUNDARY is True
    assert P5_3_Gates.UNLICENSED_CODE_IMPORT == 0
    assert P5_3_Gates.EXTERNAL_CODE_EXECUTION == 0
