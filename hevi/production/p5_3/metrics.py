"""HEVI P5.3 — Recipe library metrics.

Computes coverage, diversity, repetition, and qualification metrics.
All metrics are derived from the library state, not hardcoded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import (
    QualificationState,
    RecipeCandidate,
    RecipeFamily,
    RecipeSelectionEvidence,
)


@dataclass
class RetrievalMetrics:
    """Runtime retrieval statistics, accumulated across retrieve_with_evidence calls."""

    total_runs: int = 0
    total_candidates: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    semantic_rejections: int = 0
    constraint_rejections: int = 0
    renderer_rejections: int = 0
    no_winner_runs: int = 0

    def record(
        self,
        evidence: RecipeSelectionEvidence,
        candidates: list[RecipeCandidate],
    ) -> None:
        self.total_runs += 1
        self.total_candidates += len(evidence.candidate_recipe_ids)
        if evidence.selected_recipe_id:
            self.total_accepted += 1
        else:
            self.no_winner_runs += 1
        self.total_rejected += len(evidence.rejected_candidates)
        for reason in evidence.rejection_reasons.values():
            if reason.startswith("constraint:"):
                self.constraint_rejections += 1
            elif "CAPABILITY_MISSING" in reason:
                self.renderer_rejections += 1
            elif "lower score" in reason:
                self.semantic_rejections += 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["SEMANTIC_REJECTION_RATE"] = round(
            self.semantic_rejections / max(self.total_rejected, 1), 3
        )
        d["CONSTRAINT_REJECTION_RATE"] = round(
            self.constraint_rejections / max(self.total_rejected, 1), 3
        )
        d["RENDERER_REJECTION_RATE"] = round(
            self.renderer_rejections / max(self.total_rejected, 1), 3
        )
        return d


_retrieval_metrics = RetrievalMetrics()


def get_retrieval_metrics() -> dict[str, Any]:
    return _retrieval_metrics.to_dict()


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
        "SEMANTIC_REJECTION_RATE": get_retrieval_metrics().get("SEMANTIC_REJECTION_RATE", 0.0),
        "CONSTRAINT_REJECTION_RATE": get_retrieval_metrics().get("CONSTRAINT_REJECTION_RATE", 0.0),
        "RENDERER_REJECTION_RATE": get_retrieval_metrics().get("RENDERER_REJECTION_RATE", 0.0),
        "QUALIFIED_RECIPE_COUNT": qualified,
        "EXPERIMENTAL_RECIPE_COUNT": experimental,
        "DEPRECATED_RECIPE_COUNT": deprecated,
        "REFERENCE_DERIVED_RECIPE_COUNT": reference_derived,
        "P5_1_ACCEPT_RATE": "NOT_MEASURABLE",
        "P5_1_REJECT_RATE": "NOT_MEASURABLE",
    }


__all__ = ["compute_metrics"]
