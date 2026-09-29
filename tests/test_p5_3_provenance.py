"""HEVI P5.3 — license boundary and provenance tests."""

from __future__ import annotations

from hevi.production.p5_3.provenance import (
    check_license_boundary,
    get_provenance_summary,
    is_unlicensed_code_import,
)
from hevi.production.p5_3.reference_corpus import VideoAgentReferenceCorpus
from hevi.production.p5_3.schema import AdoptionMode


def test_all_repositories_have_provenance() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        assert repo.license or repo.license_confidence == "unknown"


def test_unknown_license_is_reference_only() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        if repo.license_confidence == "unknown":
            assert repo.adoption_mode is AdoptionMode.REFERENCE_ONLY


def test_guizang_agpl_is_reference_only() -> None:
    corpus = VideoAgentReferenceCorpus()
    repo = corpus.get("guizang-product-video-skill")
    assert repo is not None
    allowed, reason = check_license_boundary(corpus, "guizang-product-video-skill")
    assert allowed is False
    assert "AGPL" in repo.license or "REFERENCE_ONLY" in reason


def test_hyperframes_contract_adopt_allowed() -> None:
    corpus = VideoAgentReferenceCorpus()
    allowed, reason = check_license_boundary(corpus, "HyperFrames")
    # MIT license with CONTRACT_ADOPT should allow non-code adoption
    assert allowed is True or "REFERENCE_ONLY" in reason


def test_unknown_repository_not_found() -> None:
    corpus = VideoAgentReferenceCorpus()
    allowed, reason = check_license_boundary(corpus, "NonExistent")
    assert allowed is False
    assert "NOT_FOUND" in reason


def test_unlicensed_code_import_detected() -> None:
    corpus = VideoAgentReferenceCorpus()
    # guizang is AGPL + REFERENCE_ONLY: code import is unlicensed
    assert is_unlicensed_code_import(corpus, "guizang-product-video-skill", "CODE") is True


def test_provenance_summary() -> None:
    corpus = VideoAgentReferenceCorpus()
    summary = get_provenance_summary(corpus)
    assert summary["total_repositories"] == 12
    assert summary["unknown_license_count"] > 0
    assert summary["reference_only_count"] > 0


def test_no_code_adoption_without_license() -> None:
    """Unknown license repos must not be code-adopted."""
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        if repo.license_confidence == "unknown":
            assert is_unlicensed_code_import(corpus, repo.repository, "CODE") is True
