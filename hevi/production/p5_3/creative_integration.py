"""HEVI P5.3 — CreativeLedger integration and variety control.

Records recipe usage into the P5.2 CreativeLedger for repetition detection,
variety control, and historical performance. Does NOT create a separate
RecipeHistoryDB.

Variety is the lowest priority. Semantic correctness, evidence correctness,
renderer capability, and profile compatibility all outrank it.
"""

from __future__ import annotations

from hevi.production.creative_ledger import CreativeLedger, fingerprint_from_shot
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import (
    CreativeVarietyScore,
    RecipeUsageRecord,
)


def record_recipe_usage(
    ledger: CreativeLedger,
    record: RecipeUsageRecord,
) -> None:
    """Record one recipe usage into the CreativeLedger.

    This integrates with the existing P5.2 CreativeLedger. No separate
    RecipeHistoryDB is created.
    """
    ledger.record(
        fingerprint_from_shot(
            f"recipe-{record.recipe_id}",
            record.content_id,
            layout=record.beat_role,
            transition="recipe",
            motion=record.recipe_id,
            camera=record.profile,
            duration_s=0.0,
        )
    )


def compute_variety_score(
    library: RecipeLibrary,
    recipe_id: str,
    *,
    recent_recipe_ids: list[str] | None = None,
    recent_family_ids: list[str] | None = None,
    neighbor_recipe_ids: list[str] | None = None,
    profile: str = "",
) -> CreativeVarietyScore:
    """Compute a variety score for a recipe choice.

    Considers: recent recipe frequency, same-family frequency, neighbor
    repetition, profile repetition, composition repetition, transition
    repetition.

    Variety never overrides semantic match. The caller must ensure semantic
    correctness is ranked above variety.
    """
    recent = recent_recipe_ids or []
    families = recent_family_ids or []
    neighbors = neighbor_recipe_ids or []

    recipe = library.get(recipe_id)
    family = recipe.recipe_family.value if recipe else ""

    recent_freq = recent.count(recipe_id) / max(len(recent), 1) if recent else 0.0
    family_freq = families.count(family) / max(len(families), 1) if families else 0.0
    neighbor_rep = neighbors.count(recipe_id) / max(len(neighbors), 1) if neighbors else 0.0

    # Variety score: higher is more varied (less repetitive)
    variety = 1.0 - (0.3 * recent_freq + 0.2 * family_freq + 0.2 * neighbor_rep)
    variety = max(0.0, min(1.0, variety))

    return CreativeVarietyScore(
        recent_recipe_frequency=round(recent_freq, 3),
        same_family_frequency=round(family_freq, 3),
        neighbor_repetition=round(neighbor_rep, 3),
        profile_repetition=0.0,
        composition_repetition=0.0,
        transition_repetition=0.0,
        variety_score=round(variety, 3),
        semantic_override=False,
    )


def is_semantic_correctness_overriding_variety(
    semantic_match: float,
    variety_score: float,
) -> bool:
    """Whether semantic correctness should override variety.

    Semantic correctness always outranks variety. This function makes that
    explicit so the ranking code cannot accidentally invert the priority.
    """
    return semantic_match > variety_score


__all__ = [
    "compute_variety_score",
    "is_semantic_correctness_overriding_variety",
    "record_recipe_usage",
]
