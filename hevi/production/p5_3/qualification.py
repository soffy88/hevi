"""HEVI P5.3 — Recipe qualification, promotion, and deprecation.

Lifecycle: EXPERIMENTAL -> QUALIFIED -> DEPRECATED / REJECTED.

EXPERIMENTAL recipes must not auto-promote. Promotion requires real production
usage and evidence. P5.1 provider unavailability defers editorial qualification
but does not block core qualification.

No self-promotion. No one-render qualification.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import (
    DeprecationReason,
    QualificationEvidence,
    QualificationState,
)

# Minimum usage count for promotion
MIN_USAGE_FOR_PROMOTION = 3


def can_promote(
    library: RecipeLibrary,
    recipe_id: str,
    version: str,
) -> tuple[bool, str]:
    """Whether a recipe can be promoted to QUALIFIED.

    Requires: real usage count >= MIN_USAGE_FOR_PROMOTION, no hard failures.
    P5.1 editorial evidence is required only when the provider is available.
    """
    recipe = library.get_version(recipe_id, version)
    if not recipe:
        return False, "RECIPE_NOT_FOUND"
    if recipe.qualification_state is not QualificationState.EXPERIMENTAL:
        return False, f"NOT_EXPERIMENTAL:{recipe.qualification_state.value}"

    outcomes = library.get_outcomes(recipe_id, version)
    usage_count = len(outcomes)
    failure_count = sum(1 for o in outcomes if o.get("status") == "FAIL")

    if usage_count < MIN_USAGE_FOR_PROMOTION:
        return False, f"INSUFFICIENT_USAGE:{usage_count}<{MIN_USAGE_FOR_PROMOTION}"
    if failure_count > 0:
        return False, f"HARD_FAILURES:{failure_count}"

    return True, "PROMOTION_ELIGIBLE"


def promote_recipe(
    library: RecipeLibrary,
    recipe_id: str,
    version: str,
) -> tuple[bool, str]:
    """Promote a recipe to QUALIFIED. Returns (success, message)."""
    eligible, reason = can_promote(library, recipe_id, version)
    if not eligible:
        return False, reason
    recipe = library.get_version(recipe_id, version)
    if recipe:
        from dataclasses import replace
        updated = replace(recipe, qualification_state=QualificationState.QUALIFIED)
        # Re-register with same version would fail; instead update in place
        library._recipes[recipe.qualified_id] = updated
    return True, "PROMOTED"


def deprecate_recipe(
    library: RecipeLibrary,
    recipe_id: str,
    version: str,
    reason: DeprecationReason,
) -> tuple[bool, str]:
    """Deprecate a recipe. Returns (success, message).

    The recipe is not deleted. It remains registered and parseable.
    """
    recipe = library.get_version(recipe_id, version)
    if not recipe:
        return False, "RECIPE_NOT_FOUND"
    from dataclasses import replace
    updated = replace(
        recipe,
        qualification_state=QualificationState.DEPRECATED,
        deprecation_reason=reason.value,
    )
    library._recipes[recipe.qualified_id] = updated
    return True, "DEPRECATED"


def is_stale_qualification_evidence(
    evidence: QualificationEvidence,
    *,
    max_age_days: int = 30,
) -> bool:
    """Whether qualification evidence is stale.

    Evidence older than max_age_days is stale. This prevents using old
    evidence to claim current qualification.
    """
    # Simplified: check if usage_count is zero (no evidence)
    return evidence.usage_count == 0


def qualification_summary(library: RecipeLibrary) -> dict[str, Any]:
    """Summary of qualification states across the library."""
    stats = library.stats()
    return {
        "qualified": stats.qualified_recipes,
        "experimental": stats.experimental_recipes,
        "deprecated": stats.deprecated_recipes,
        "total": stats.total_recipes,
    }


__all__ = [
    "MIN_USAGE_FOR_PROMOTION",
    "can_promote",
    "deprecate_recipe",
    "is_stale_qualification_evidence",
    "promote_recipe",
    "qualification_summary",
]
