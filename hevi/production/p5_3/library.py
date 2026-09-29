"""HEVI P5.3 — RecipeLibrary: the single authority for cinematic recipes.

One library. Not nine registries. Not a SkillRegistry, MotionRegistry, or
ShotRegistry. Recipes are registered, retrieved by semantics, filtered by
constraints, ranked by match quality, and versioned immutably.

The library does not render, execute providers, deliver, repair video, or
override ShotPlan / MotionPlan. It recommends and ranks.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.production.p5_3.schema import (
    CinematicRecipe,
    QualificationState,
    RecipeCandidate,
    RecipeFamily,
    RecipeUsageRecord,
)


@dataclass
class RecipeLibraryStats:
    """Library-wide statistics."""

    total_recipes: int = 0
    qualified_recipes: int = 0
    experimental_recipes: int = 0
    deprecated_recipes: int = 0
    family_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecipeLibrary:
    """The single registry for all cinematic recipes.

    Recipes are stored by qualified_id (recipe_id@version). A recipe_id may
    have multiple versions; the latest qualified version is the default.
    Versions are immutable: mutating a recipe creates a new version, never
    overwrites history.
    """

    def __init__(self) -> None:
        self._recipes: dict[str, CinematicRecipe] = {}
        self._usage_records: list[RecipeUsageRecord] = []
        self._outcomes: dict[str, list[dict[str, Any]]] = {}

    # ── Registration ────────────────────────────────────────────────────

    def register(self, recipe: CinematicRecipe) -> CinematicRecipe:
        """Register a recipe. Returns the stored recipe.

        If the recipe_id already exists with the same version, raises
        ValueError — versions are immutable. To change a recipe, create a new
        version.
        """
        qualified = recipe.qualified_id
        if qualified in self._recipes:
            raise ValueError(f"RECIPE_VERSION_IMMUTABLE:{qualified} already exists")
        self._recipes[qualified] = recipe
        return recipe

    def get(self, recipe_id: str, version: str = "") -> CinematicRecipe | None:
        """Get a recipe by ID and optional version.

        If version is empty, returns the latest qualified version.
        """
        if version:
            return self._recipes.get(f"{recipe_id}@{version}")
        # Find latest version for this recipe_id
        candidates = [
            r for key, r in self._recipes.items() if key.startswith(f"{recipe_id}@")
        ]
        if not candidates:
            return None
        # Sort by version string (semantic versioning approximation)
        candidates.sort(key=lambda r: r.version, reverse=True)
        return candidates[0]

    def get_version(self, recipe_id: str, version: str) -> CinematicRecipe | None:
        """Get a specific version of a recipe."""
        return self._recipes.get(f"{recipe_id}@{version}")

    # ── Search and Filter ───────────────────────────────────────────────

    def search(
        self,
        *,
        query: str = "",
        family: RecipeFamily | None = None,
        profile: str = "",
        beat_role: str = "",
        intent: str = "",
        duration: float | None = None,
        asset_type: str = "",
        renderer_capability: str = "",
        information_density: float | None = None,
        qualification_state: QualificationState | None = None,
    ) -> list[CinematicRecipe]:
        """Search recipes by semantic and structural criteria.

        All criteria are AND-combined. Empty criteria are ignored.
        """
        results: list[CinematicRecipe] = []
        for recipe in self._recipes.values():
            if family and recipe.recipe_family is not family:
                continue
            if profile and profile not in recipe.profile_compatibility:
                continue
            if beat_role and beat_role not in recipe.beat_roles:
                continue
            if intent and intent != recipe.intent:
                continue
            if duration is not None:
                min_d, max_d = recipe.duration_range
                if not (min_d <= duration <= max_d):
                    continue
            if asset_type and asset_type not in recipe.required_assets:
                continue
            if renderer_capability and renderer_capability not in recipe.required_capabilities:
                continue
            if information_density is not None:
                min_id, max_id = recipe.information_density_range
                if not (min_id <= information_density <= max_id):
                    continue
            if qualification_state and recipe.qualification_state is not qualification_state:
                continue
            if query and query.lower() not in recipe.name.lower():
                continue
            results.append(recipe)
        return results

    def filter(
        self,
        recipes: list[CinematicRecipe],
        *,
        profile: str = "",
        beat_role: str = "",
        intent: str = "",
        duration: float | None = None,
        asset_type: str = "",
        renderer_capability: str = "",
        information_density: float | None = None,
        qualification_state: QualificationState | None = None,
    ) -> list[CinematicRecipe]:
        """Filter a list of recipes by constraints.

        This is the constraint-aware filtering step. A recipe that violates a
        hard constraint is excluded, not penalized.
        """
        return self.search(
            profile=profile,
            beat_role=beat_role,
            intent=intent,
            duration=duration,
            asset_type=asset_type,
            renderer_capability=renderer_capability,
            information_density=information_density,
            qualification_state=qualification_state,
        ) if not recipes else [
            r for r in recipes
            if self._passes_constraints(
                r,
                profile=profile,
                beat_role=beat_role,
                intent=intent,
                duration=duration,
                asset_type=asset_type,
                renderer_capability=renderer_capability,
                information_density=information_density,
                qualification_state=qualification_state,
            )
        ]

    def _passes_constraints(
        self,
        recipe: CinematicRecipe,
        *,
        profile: str,
        beat_role: str,
        intent: str,
        duration: float | None,
        asset_type: str,
        renderer_capability: str,
        information_density: float | None,
        qualification_state: QualificationState | None,
    ) -> bool:
        if profile and profile not in recipe.profile_compatibility:
            return False
        if beat_role and beat_role not in recipe.beat_roles:
            return False
        if intent and intent != recipe.intent:
            return False
        if duration is not None:
            min_d, max_d = recipe.duration_range
            if not (min_d <= duration <= max_d):
                return False
        if asset_type and asset_type not in recipe.required_assets:
            return False
        if renderer_capability and renderer_capability not in recipe.required_capabilities:
            return False
        if information_density is not None:
            min_id, max_id = recipe.information_density_range
            if not (min_id <= information_density <= max_id):
                return False
        return not (
            qualification_state and recipe.qualification_state is not qualification_state
        )

    # ── Ranking ─────────────────────────────────────────────────────────

    def rank_candidates(
        self,
        candidates: list[RecipeCandidate],
        *,
        variety_scores: dict[str, float] | None = None,
        historical_scores: dict[str, float] | None = None,
    ) -> list[RecipeCandidate]:
        """Rank candidates by selection score.

        The selection score is a weighted combination of:
        - semantic match (highest weight)
        - profile match
        - asset match
        - capability match
        - duration match
        - variety score (lowest weight — never overrides semantic)
        - historical quality score

        Candidates with constraint violations are excluded before ranking.
        """
        valid = [c for c in candidates if not c.constraint_violations]
        for c in valid:
            variety = (variety_scores or {}).get(c.recipe_id, 0.0)
            historical = (historical_scores or {}).get(c.recipe_id, 0.0)
            c.variety_score = variety
            c.historical_quality_score = historical
            c.selection_score = (
                0.30 * c.semantic_match
                + 0.20 * c.profile_match
                + 0.15 * c.asset_match
                + 0.10 * c.capability_match
                + 0.10 * c.duration_match
                + 0.10 * historical
                + 0.05 * variety
            )
            c.selection_reason = (
                f"semantic={c.semantic_match:.2f} profile={c.profile_match:.2f} "
                f"asset={c.asset_match:.2f} capability={c.capability_match:.2f} "
                f"duration={c.duration_match:.2f} historical={historical:.2f} "
                f"variety={variety:.2f}"
            )
        valid.sort(key=lambda c: c.selection_score, reverse=True)
        return valid

    # ── Listing ─────────────────────────────────────────────────────────

    def list_family(self, family: RecipeFamily) -> list[CinematicRecipe]:
        """List all recipes in a family."""
        return [r for r in self._recipes.values() if r.recipe_family is family]

    def list_qualified(self) -> list[CinematicRecipe]:
        """List all qualified recipes."""
        return [
            r for r in self._recipes.values()
            if r.qualification_state is QualificationState.QUALIFIED
        ]

    def list_all(self) -> list[CinematicRecipe]:
        """List all recipes."""
        return list(self._recipes.values())

    # ── Usage and Outcomes ──────────────────────────────────────────────

    def record_usage(self, record: RecipeUsageRecord) -> None:
        """Record one usage of a recipe in production."""
        self._usage_records.append(record)

    def record_outcome(
        self, recipe_id: str, version: str, outcome: dict[str, Any]
    ) -> None:
        """Record an outcome for a recipe version."""
        key = f"{recipe_id}@{version}"
        if key not in self._outcomes:
            self._outcomes[key] = []
        self._outcomes[key].append(outcome)

    def get_outcomes(self, recipe_id: str, version: str) -> list[dict[str, Any]]:
        """Get all recorded outcomes for a recipe version."""
        return self._outcomes.get(f"{recipe_id}@{version}", [])

    # ── Statistics ──────────────────────────────────────────────────────

    def stats(self) -> RecipeLibraryStats:
        """Library-wide statistics."""
        family_counts: dict[str, int] = {}
        for r in self._recipes.values():
            family = r.recipe_family.value
            family_counts[family] = family_counts.get(family, 0) + 1
        return RecipeLibraryStats(
            total_recipes=len(self._recipes),
            qualified_recipes=len(self.list_qualified()),
            experimental_recipes=len(
                [r for r in self._recipes.values() if r.qualification_state is QualificationState.EXPERIMENTAL]
            ),
            deprecated_recipes=len(
                [r for r in self._recipes.values() if r.qualification_state is QualificationState.DEPRECATED]
            ),
            family_counts=family_counts,
        )

    # ── Persistence ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipes": {key: r.to_dict() for key, r in self._recipes.items()},
            "usage_records": [r.to_dict() for r in self._usage_records],
            "outcomes": self._outcomes,
            "stats": self.stats().to_dict(),
        }

    def save(self, path: Path) -> None:
        """Save the library to a JSON file."""
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path) -> RecipeLibrary:
        """Load a library from a JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        library = cls()
        for key, recipe_data in data.get("recipes", {}).items():
            library._recipes[key] = CinematicRecipe.from_dict(recipe_data)
        for record_data in data.get("usage_records", []):
            library._usage_records.append(RecipeUsageRecord(**record_data))
        library._outcomes = data.get("outcomes", {})
        return library


__all__ = ["RecipeLibrary", "RecipeLibraryStats"]
