import pytest
from hevi.production.p5_3_reference import (
    REFERENCE_CORPUS,
    REFERENCE_GRAMMAR,
    REFERENCE_VIDEO_COPYING,
    UNLICENSED_CODE_IMPORT,
    EXTERNAL_CODE_EXECUTION,
    ReferenceVideoAnalysis,
    AntiCopyGuard,
    ReferenceRepository
)
from hevi.production.p5_3_corpus import VideoAgentReferenceCorpus, AdoptionMode

def test_gates():
    assert REFERENCE_CORPUS is True
    assert REFERENCE_GRAMMAR is True
    assert REFERENCE_VIDEO_COPYING == 0
    assert UNLICENSED_CODE_IMPORT == 0
    assert EXTERNAL_CODE_EXECUTION == 0

def test_corpus_loading():
    corpus = VideoAgentReferenceCorpus()
    assert len(corpus.list_references()) >= 12
    
    # Check specific seeds
    om = corpus.get_reference("OpenMontage")
    assert om is not None
    assert om.adoption_mode == AdoptionMode.REFERENCE_ONLY
    
    hf = corpus.get_reference("HyperFrames")
    assert hf is not None
    assert hf.license == "MIT"
    assert hf.adoption_mode == AdoptionMode.CODE_ADOPT_ALLOWED

def test_reference_grammar_extraction():
    grammar = ReferenceVideoAnalysis.extract_grammar("dummy_source")
    assert grammar.pacing.rhythm_type == "steady"
    assert "medium" in grammar.composition.framing_types
    assert grammar.narrative.phases == ["hook", "body", "cta"]

def test_anti_copy_guards():
    ref_seq = ["shot_1", "shot_2"]
    gen_seq_diff = ["shot_3", "shot_4"]
    gen_seq_same = ["shot_1", "shot_2"]
    
    assert AntiCopyGuard.check_ordered_shot_sequence(gen_seq_diff, ref_seq) is True
    assert AntiCopyGuard.check_ordered_shot_sequence(gen_seq_same, ref_seq) is False

def test_reference_repository():
    corpus = VideoAgentReferenceCorpus()
    repo = ReferenceRepository(corpus)
    
    assert repo.resolve_reference("OpenMontage") is True
    assert repo.resolve_reference("HyperFrames") is True
    assert repo.resolve_reference("UnknownReference") is False
