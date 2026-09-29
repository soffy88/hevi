"""HEVI P5.3 — License boundary and provenance.

Every external source must record: repository, commit/revision, license,
source_file_or_doc, adoption_type.

Adoption types: IDEA, CONTRACT, RECIPE_STRUCTURE, PARAMETER_VALUES, CODE, ASSET.

Unknown license: REFERENCE_ONLY. No code import.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p5_3.reference_corpus import VideoAgentReferenceCorpus
from hevi.production.p5_3.schema import AdoptionMode

# Adoption type definitions
ADOPTION_TYPES: dict[str, str] = {
    "IDEA": "Abstract concept, no code",
    "CONTRACT": "Interface/contract pattern",
    "RECIPE_STRUCTURE": "Recipe structure and parameters",
    "PARAMETER_VALUES": "Specific parameter values",
    "CODE": "Source code",
    "ASSET": "Media asset",
}


def check_license_boundary(
    corpus: VideoAgentReferenceCorpus,
    repository: str,
) -> tuple[bool, str]:
    """Check whether a repository's license permits the requested adoption.

    Returns (allowed, reason). Unknown licenses are REFERENCE_ONLY.
    """
    repo = corpus.get(repository)
    if repo is None:
        return False, f"REPOSITORY_NOT_FOUND:{repository}"
    if repo.license_confidence == "unknown":
        return False, f"LICENSE_UNKNOWN:{repository}"
    if repo.adoption_mode is AdoptionMode.REJECT:
        return False, f"ADOPTION_REJECTED:{repository}"
    if repo.adoption_mode is AdoptionMode.REFERENCE_ONLY:
        return False, f"REFERENCE_ONLY:{repository}"
    return True, "LICENSE_OK"


def is_unlicensed_code_import(
    corpus: VideoAgentReferenceCorpus,
    repository: str,
    adoption_type: str,
) -> bool:
    """Whether importing code from a repository would violate its license."""
    allowed, _ = check_license_boundary(corpus, repository)
    if not allowed:
        return True
    if adoption_type == "CODE":
        repo = corpus.get(repository)
        if repo and repo.license_confidence == "unknown":
            return True
    return False


def get_provenance_summary(corpus: VideoAgentReferenceCorpus) -> dict[str, Any]:
    """Summary of all provenance records."""
    repos = corpus.list_all()
    return {
        "total_repositories": len(repos),
        "by_adoption_mode": {
            mode.value: len(corpus.list_by_adoption(mode))
            for mode in AdoptionMode
        },
        "recipe_sources": len(corpus.list_recipe_sources()),
        "unknown_license_count": len(
            [r for r in repos if r.license_confidence == "unknown"]
        ),
        "reference_only_count": len(
            [r for r in repos if r.adoption_mode is AdoptionMode.REFERENCE_ONLY]
        ),
    }


__all__ = [
    "ADOPTION_TYPES",
    "check_license_boundary",
    "get_provenance_summary",
    "is_unlicensed_code_import",
]
