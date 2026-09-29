"""HEVI P5.3 — Recipe versioning: immutable, deprecatable, historically reproducible.

A recipe version is immutable. Mutating a recipe creates a new version; it never
overwrites history. Old versions remain parseable forever — a historical project
that references recipe_id@1.0.0 must still resolve even after 2.0.0 exists.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from hevi.production.p5_3.schema import (
    CinematicRecipe,
    DeprecationReason,
    QualificationState,
)

# Forward reference to avoid circular import at runtime; RecipeLibrary does not
# import from this module, so the import below is safe for type-checking.
if False:  # TYPE_CHECKING
    from hevi.production.p5_3.library import RecipeLibrary


def bump_version(current: str, *, major: bool = False, minor: bool = False) -> str:
    """Compute the next version string.

    Default is a patch bump. ``minor`` bumps the minor digit, ``major`` the major
    digit. A recipe that changes its canonical structure should bump minor at
    least; a change that alters meaning should bump major.
    """
    parts = current.split(".")
    while len(parts) < 3:
        parts.append("0")
    major_n, minor_n, patch_n = (int(parts[0]), int(parts[1]), int(parts[2]))
    if major:
        return f"{major_n + 1}.0.0"
    if minor:
        return f"{major_n}.{minor_n + 1}.0"
    return f"{major_n}.{minor_n}.{patch_n + 1}"


def derive_new_version(
    recipe: CinematicRecipe,
    changes: dict[str, Any],
    *,
    major: bool = False,
    minor: bool = True,
) -> CinematicRecipe:
    """Create a new version of a recipe with applied changes.

    The original is never modified. The new version gets a bumped version string
    and the applied changes. Provenance is updated to record the derivation.
    """
    new_version = bump_version(recipe.version, major=major, minor=minor)
    return replace(recipe, version=new_version, **changes)


def deprecate_recipe(
    library: RecipeLibrary,
    recipe_id: str,
    version: str,
    reason: DeprecationReason,
    *,
    timestamp: str = "",
) -> CinematicRecipe:
    """Deprecate a recipe in the library.

    The recipe is not deleted. It remains registered and parseable. Historical
    projects that reference it still resolve.
    """
    recipe = library.get_version(recipe_id, version)
    if recipe is None:
        raise ValueError(f"RECIPE_NOT_FOUND:{recipe_id}@{version}")
    updated = replace(
        recipe,
        qualification_state=QualificationState.DEPRECATED,
        deprecated_at=timestamp,
        deprecation_reason=reason.value,
    )
    library._recipes[recipe.qualified_id] = updated
    return updated


def is_historical_version_available(
    library: Any, recipe_id: str, version: str
) -> bool:
    """Check whether a specific historical version is still available.

    This is the historical reproducibility check: a project that pinned an old
    version must still be able to resolve it.
    """
    return library.get_version(recipe_id, version) is not None


__all__ = [
    "bump_version",
    "deprecate_recipe",
    "derive_new_version",
    "is_historical_version_available",
]
