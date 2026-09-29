"""HEVI P5.3 — Semantic recipe retrieval and constraint-aware filtering.

Retrieval consumes the existing semantic layer: VisualBeat, Profile, available
assets, ShotReadiness, renderer capabilities, and CreativeLedger. It produces
RecipeCandidate objects ranked by match quality.

No random selection. Every candidate is scored and ranked.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.profile_grammar import profile_recipe_preferences
from hevi.production.p5_3.schema import (
    CinematicRecipe,
    RecipeCandidate,
    RecipeSelectionEvidence,
)


def retrieve_recipes(
    library: RecipeLibrary,
    beat: VisualBeat,
    *,
    profile_id: str = "",
    available_assets: list[str] | None = None,
    renderer_capabilities: list[str] | None = None,
    duration: float | None = None,
    information_density: float | None = None,
    qualification_state: Any = None,
) -> list[RecipeCandidate]:
    """Retrieve and rank recipe candidates for a visual beat.

    The retrieval is semantic: it matches the beat's shot_role, intent, and
    narrative_phase against recipe beat_roles, intent, and semantic_roles. It
    then filters by hard constraints (profile, assets, capabilities, duration,
    density) and ranks the survivors.

    No random selection. Every candidate is scored.
    """
    available_assets = available_assets or []
    renderer_capabilities = renderer_capabilities or []

    # Step 1: semantic search. Try the exact beat_role first; if nothing matches,
    # fall back to a broader search so a beat is never left without candidates.
    # A recipe that suits the profile and the assets is still a recipe that suits
    # the beat, even when the role label differs.
    search_kwargs: dict[str, Any] = {
        "profile": profile_id,
        "duration": duration,
        "asset_type": available_assets[0] if available_assets else "",
        "renderer_capability": renderer_capabilities[0] if renderer_capabilities else "",
        "information_density": information_density,
        "qualification_state": qualification_state,
    }
    candidates_recipes = library.search(beat_role=beat.shot_role, **search_kwargs)
    if not candidates_recipes:
        candidates_recipes = library.search(**search_kwargs)

    # Step 2: score each candidate
    scored: list[RecipeCandidate] = []
    for recipe in candidates_recipes:
        semantic = _semantic_match(recipe, beat)
        profile_match = _profile_match(recipe, profile_id)
        asset_match = _asset_match(recipe, available_assets)
        capability_match = _capability_match(recipe, renderer_capabilities)
        duration_match = _duration_match(recipe, duration)

        violations = _constraint_violations(
            recipe, profile_id, available_assets, renderer_capabilities,
            duration, information_density,
        )

        scored.append(RecipeCandidate(
            recipe_id=recipe.recipe_id,
            version=recipe.version,
            semantic_match=semantic,
            profile_match=profile_match,
            asset_match=asset_match,
            capability_match=capability_match,
            duration_match=duration_match,
            constraint_violations=violations,
        ))

    # Step 3: rank (excludes candidates with constraint violations)
    return library.rank_candidates(scored)


def _semantic_match(recipe: CinematicRecipe, beat: VisualBeat) -> float:
    """How well the recipe's semantics match the beat."""
    score = 0.0
    if beat.shot_role and beat.shot_role in recipe.beat_roles:
        score += 0.4
    if beat.intent_id and beat.intent_id == recipe.intent:
        score += 0.3
    if beat.motion_purpose and beat.motion_purpose in recipe.semantic_roles:
        score += 0.2
    if beat.narrative_phase and beat.narrative_phase in recipe.beat_roles:
        score += 0.1
    return min(1.0, score)


def _profile_match(recipe: CinematicRecipe, profile_id: str) -> float:
    """How well the recipe matches the profile."""
    if not profile_id:
        return 0.5
    if profile_id in recipe.profile_compatibility:
        return 1.0
    prefs = profile_recipe_preferences(profile_id)
    if recipe.recipe_id in prefs.get("preferred_recipes", []):
        return 0.8
    if recipe.recipe_family.value in prefs.get("preferred_families", []):
        return 0.6
    return 0.2


def _asset_match(recipe: CinematicRecipe, available_assets: list[str]) -> float:
    """How well the recipe's required assets are available."""
    if not recipe.required_assets:
        return 0.5
    if not available_assets:
        return 0.0
    matched = sum(1 for a in recipe.required_assets if a in available_assets)
    return matched / len(recipe.required_assets)


def _capability_match(
    recipe: CinematicRecipe, renderer_capabilities: list[str]
) -> float:
    """How well the recipe's required capabilities are available."""
    if not recipe.required_capabilities:
        return 0.5
    if not renderer_capabilities:
        return 0.0
    matched = sum(1 for c in recipe.required_capabilities if c in renderer_capabilities)
    return matched / len(recipe.required_capabilities)


def _duration_match(recipe: CinematicRecipe, duration: float | None) -> float:
    """How well the recipe's duration range fits the requested duration."""
    if duration is None:
        return 0.5
    min_d, max_d = recipe.duration_range
    if min_d <= duration <= max_d:
        return 1.0
    # Partial credit for nearby ranges
    mid = (min_d + max_d) / 2.0
    dist = abs(duration - mid)
    return max(0.0, 1.0 - dist / max(mid, 1.0))


def _constraint_violations(
    recipe: CinematicRecipe,
    profile_id: str,
    available_assets: list[str],
    renderer_capabilities: list[str],
    duration: float | None,
    information_density: float | None,
) -> list[str]:
    """Hard constraint violations. A violation excludes the candidate."""
    violations: list[str] = []
    if profile_id and profile_id not in recipe.profile_compatibility:
        violations.append(f"PROFILE_INCOMPATIBLE:{profile_id}")
    violations.extend(
        f"ASSET_MISSING:{asset}"
        for asset in recipe.required_assets
        if available_assets and asset not in available_assets
    )
    violations.extend(
        f"CAPABILITY_MISSING:{cap}"
        for cap in recipe.required_capabilities
        if renderer_capabilities and cap not in renderer_capabilities
    )
    if duration is not None:
        min_d, max_d = recipe.duration_range
        if not (min_d <= duration <= max_d):
            violations.append(f"DURATION_OUT_OF_RANGE:{duration}")
    if information_density is not None:
        min_id, max_id = recipe.information_density_range
        if not (min_id <= information_density <= max_id):
            violations.append(f"DENSITY_OUT_OF_RANGE:{information_density}")
    return violations


def retrieve_with_evidence(
    library: RecipeLibrary,
    beat: VisualBeat,
    *,
    profile_id: str = "",
    available_assets: list[str] | None = None,
    renderer_capabilities: list[str] | None = None,
    duration: float | None = None,
    information_density: float | None = None,
    qualification_state: Any = None,
) -> tuple[list[RecipeCandidate], RecipeSelectionEvidence]:
    """Retrieve candidates and record why the winner won.

    This is the same canonical path as :func:`retrieve_recipes` — same search,
    same scoring, same ranking, same order. The only addition is that the
    decision is written down as a :class:`RecipeSelectionEvidence` so both
    questions are answerable afterwards: WHY_THIS_RECIPE and
    WHY_NOT_THE_OTHER_RECIPES.

    Deterministic: identical inputs produce identical candidates in identical
    order with identical evidence, except for the timestamp. No random selection
    anywhere in the path.
    """
    import datetime

    candidates = retrieve_recipes(
        library,
        beat,
        profile_id=profile_id,
        available_assets=available_assets,
        renderer_capabilities=renderer_capabilities,
        duration=duration,
        information_density=information_density,
        qualification_state=qualification_state,
    )

    # Ranked order is the selection order. The winner is candidates[0]; every
    # other candidate is rejected, and the reason is its own score deficit —
    # recorded verbatim so the trace needs no reconstruction.
    winner = candidates[0] if candidates else None
    rejected: list[str] = []
    rejection_reasons: dict[str, str] = {}
    for candidate in candidates[1:]:
        rejected.append(candidate.recipe_id)
        if candidate.constraint_violations:
            # Candidates with violations never reach ranking; if one appears
            # here it is recorded as a constraint rejection.
            rejection_reasons[candidate.recipe_id] = (
                "constraint: " + "; ".join(candidate.constraint_violations)
            )
        else:
            rejection_reasons[candidate.recipe_id] = (
                f"lower score {candidate.selection_score:.3f} vs "
                f"{winner.selection_score:.3f}" if winner else "no winner"
            )

    constraint_matches: list[str] = []
    if profile_id:
        constraint_matches.append(f"profile={profile_id}")
    if duration is not None:
        constraint_matches.append(f"duration={duration}")
    if available_assets:
        constraint_matches.append(f"assets={len(available_assets)}")
    if renderer_capabilities:
        constraint_matches.append(f"capabilities={len(renderer_capabilities)}")

    evidence = RecipeSelectionEvidence(
        visual_beat_id=beat.beat_id,
        candidate_recipe_ids=[c.recipe_id for c in candidates],
        selected_recipe_id=winner.recipe_id if winner else "",
        selected_version=winner.version if winner else "",
        selection_factors=(
            {
                "semantic_match": winner.semantic_match,
                "profile_match": winner.profile_match,
                "asset_match": winner.asset_match,
                "capability_match": winner.capability_match,
                "duration_match": winner.duration_match,
                "variety_score": winner.variety_score,
                "historical_quality_score": winner.historical_quality_score,
                "selection_score": winner.selection_score,
            }
            if winner
            else {}
        ),
        rejected_candidates=rejected,
        rejection_reasons=rejection_reasons,
        creative_variety_context={"candidate_count": len(candidates)},
        historical_evidence={
            "selection_reason": winner.selection_reason if winner else ""
        },
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
    )
    return candidates, evidence


__all__ = ["retrieve_recipes", "retrieve_with_evidence"]
