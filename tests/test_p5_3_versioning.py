"""HEVI P5.3 — versioning tests: immutable, deprecatable, historically reproducible."""

from __future__ import annotations

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    DeprecationReason,
    QualificationState,
    RecipeFamily,
)
from hevi.production.p5_3.versioning import (
    bump_version,
    deprecate_recipe,
    derive_new_version,
    is_historical_version_available,
)


def _recipe(version: str = "1.0.0", **kwargs) -> CinematicRecipe:
    defaults = dict(
        recipe_id="COMPOSITION.CENTERED_HERO",
        version=version,
        recipe_family=RecipeFamily.COMPOSITION,
        name="Centered Hero",
        description="test",
    )
    defaults.update(kwargs)
    return CinematicRecipe(**defaults)


def test_bump_version_patch() -> None:
    assert bump_version("1.0.0") == "1.0.1"
    assert bump_version("1.0.9") == "1.0.10"


def test_bump_version_minor() -> None:
    assert bump_version("1.0.0", minor=True) == "1.1.0"


def test_bump_version_major() -> None:
    assert bump_version("1.0.0", major=True) == "2.0.0"


def test_derive_new_version_creates_new() -> None:
    r = _recipe()
    new = derive_new_version(r, {"name": "Updated"})
    assert new.version == "1.1.0"
    assert new.name == "Updated"
    # Original is unchanged
    assert r.version == "1.0.0"
    assert r.name == "Centered Hero"


def test_version_immutability() -> None:
    """Mutating a recipe creates a new version, never overwrites history."""
    lib = RecipeLibrary()
    lib.register(_recipe(version="1.0.0"))
    new = derive_new_version(_recipe(version="1.0.0"), {"name": "V2"})
    lib.register(new)
    # Both versions exist
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0") is not None
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.1.0") is not None
    # Old version is unchanged
    assert lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0").name == "Centered Hero"


def test_deprecate_recipe() -> None:
    lib = RecipeLibrary()
    lib.register(_recipe())
    deprecate_recipe(lib, "COMPOSITION.CENTERED_HERO", "1.0.0", DeprecationReason.OVERUSE)
    r = lib.get_version("COMPOSITION.CENTERED_HERO", "1.0.0")
    assert r.qualification_state is QualificationState.DEPRECATED
    assert r.deprecation_reason == "OVERUSE"


def test_deprecated_recipe_still_parseable() -> None:
    """Historical projects must still resolve old versions."""
    lib = RecipeLibrary()
    lib.register(_recipe())
    deprecate_recipe(lib, "COMPOSITION.CENTERED_HERO", "1.0.0", DeprecationReason.OVERUSE)
    assert is_historical_version_available(lib, "COMPOSITION.CENTERED_HERO", "1.0.0")


def test_deprecation_reasons() -> None:
    reasons = [r.value for r in DeprecationReason]
    assert "QUALITY_REGRESSION" in reasons
    assert "RENDERER_INCOMPATIBILITY" in reasons
    assert "OVERUSE" in reasons
    assert "PROFILE_MISMATCH" in reasons
    assert "ACCESSIBILITY_ISSUE" in reasons
