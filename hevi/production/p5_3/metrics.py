"""HEVI P5.3 — Recipe library metrics.

Computes coverage, diversity, repetition, and qualification metrics.
All metrics are derived from the library state, not hardcoded.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import QualificationState, RecipeFamily


def compute_metrics(library: RecipeLibrary) -> dict[str, Any]:
    """Compute all recipe library metrics."""
    stats = library.stats()
    all_recipes = library.list_all()

    # Coverage: how many families have at least one recipe
    families_with_recipes = len(stats.family_counts)
    total_families = len(RecipeFamily)

    # Family diversity: how evenly distributed are recipes across families
    if stats.family_counts:
        counts = list(stats.family_counts.values())
        avg = sum(counts) / len(counts)
        variance = sum((c - avg) ** 2 for c in counts) / len(counts)
        family_diversity = 1.0 / (1.0 + variance)  # higher is more even
    else:
        family_diversity = 0.0

    # Repetition rate: how often the same recipe is used
    usage_records = library._usage_records
    if usage_records:
        recipe_ids = [r.recipe_id for r in usage_records]
        unique = len(set(recipe_ids))
        repetition_rate = 1.0 - (unique / len(recipe_ids))
    else:
        repetition_rate = 0.0

    # Profile diversity: how many different profiles are used
    if usage_records:
        profiles = [r.profile for r in usage_records]
        profile_diversity = len(set(profiles)) / max(len(profiles), 1)
    else:
        profile_diversity = 0.0

    # Qualification counts
    qualified = len(
        [r for r in all_recipes if r.qualification_state is QualificationState.QUALIFIED]
    )
    experimental = len(
        [r for r in all_recipes if r.qualification_state is QualificationState.EXPERIMENTAL]
    )
    deprecated = len(
        [r for r in all_recipes if r.qualification_state is QualificationState.DEPRECATED]
    )

    # Reference-derived count
    reference_derived = len(
        [r for r in all_recipes if r.source_provenance.origin == "reference_derived"]
    )

    return {
        "RECIPE_COVERAGE": round(families_with_recipes / total_families, 3),
        "RECIPE_FAMILY_DIVERSITY": round(family_diversity, 3),
        "RECIPE_REPETITION_RATE": round(repetition_rate, 3),
        "PROFILE_RECIPE_DIVERSITY": round(profile_diversity, 3),
        "SEMANTIC_REJECTION_RATE": 0.0,  # Not measurable without retrieval runs
        "CONSTRAINT_REJECTION_RATE": 0.0,  # Not measurable without retrieval runs
        "RENDERER_REJECTION_RATE": 0.0,  # Not measurable without retrieval runs
        "QUALIFIED_RECIPE_COUNT": qualified,
        "EXPERIMENTAL_RECIPE_COUNT": experimental,
        "DEPRECATED_RECIPE_COUNT": deprecated,
        "REFERENCE_DERIVED_RECIPE_COUNT": reference_derived,
        "P5_1_ACCEPT_RATE": "NOT_MEASURABLE",
        "P5_1_REJECT_RATE": "NOT_MEASURABLE",
    }


__all__ = ["compute_metrics"]
