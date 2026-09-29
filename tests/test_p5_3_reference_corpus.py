"""HEVI P5.3 — reference corpus tests: read-only, no auto-execution."""

from __future__ import annotations

from hevi.production.p5_3.reference_corpus import VideoAgentReferenceCorpus
from hevi.production.p5_3.schema import AdoptionMode


def test_corpus_has_12_repositories() -> None:
    corpus = VideoAgentReferenceCorpus()
    assert corpus.count() == 12


def test_all_repositories_have_license() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        assert repo.license or repo.license_confidence == "unknown"


def test_all_repositories_are_read_only_by_default() -> None:
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        assert repo.adoption_mode in (
            AdoptionMode.REFERENCE_ONLY,
            AdoptionMode.CONTRACT_ADOPT,
            AdoptionMode.RECIPE_SOURCE,
        )


def test_no_auto_execution() -> None:
    """Corpus entries must not trigger clone/install/exec."""
    corpus = VideoAgentReferenceCorpus()
    for repo in corpus.list_all():
        # No repository should have an execution command
        assert "curl" not in str(repo.security_notes).lower()
        assert "npm install" not in str(repo.security_notes).lower()
        assert "pip install" not in str(repo.security_notes).lower()


def test_recipe_sources_are_identified() -> None:
    corpus = VideoAgentReferenceCorpus()
    sources = corpus.list_recipe_sources()
    assert len(sources) > 0
    for repo in sources:
        assert repo.recipe_sources


def test_get_repository() -> None:
    corpus = VideoAgentReferenceCorpus()
    repo = corpus.get("HyperFrames")
    assert repo is not None
    assert repo.repository == "HyperFrames"


def test_get_unknown_repository() -> None:
    corpus = VideoAgentReferenceCorpus()
    assert corpus.get("NonExistent") is None


def test_guizang_is_reference_only() -> None:
    """AGPL-3.0 repository must be reference-only."""
    corpus = VideoAgentReferenceCorpus()
    repo = corpus.get("guizang-product-video-skill")
    assert repo is not None
    assert repo.adoption_mode is AdoptionMode.REFERENCE_ONLY
    assert "AGPL" in repo.license
