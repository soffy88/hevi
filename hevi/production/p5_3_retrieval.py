from typing import List, Dict, Any, Tuple, Optional
from hevi.production.p5_3_types import CinematicRecipe, RecipeSelectionEvidence, RecipeFamily
from hevi.production.p5_3_library import RecipeLibrary

def retrieve_recipes(
    query_semantics: str,
    active_constraints: List[str],
    family: Optional[RecipeFamily] = None
) -> List[Tuple[CinematicRecipe, RecipeSelectionEvidence]]:
    """
    Retrieve recipes based on semantic relevance and constraints.
    Returns ranked recipes with selection evidence.
    Random selection is explicitly avoided (score + ID deterministic sort).
    """
    library = RecipeLibrary()
    candidates = library.get_all()
    
    if family:
        candidates = [r for r in candidates if r.family == family]

    results = []
    for recipe in candidates:
        score = 0.0
        matched_constraints = []
        
        # Exact constraint matches increase score heavily
        for constraint in recipe.constraints:
            if constraint in active_constraints:
                score += 1.0
                matched_constraints.append(constraint)
            else:
                # Penalty for unmet constraint
                score -= 0.5
                
        # Semantic dummy check
        query_words = set(query_semantics.lower().split())
        desc_words = set(recipe.description.lower().split())
        overlap = query_words.intersection(desc_words)
        score += len(overlap) * 0.1
        
        if score > -100: # allow some negative scoring to test filtering if needed, but we keep everything ranked
            evidence = RecipeSelectionEvidence(
                recipe_id=recipe.id,
                score=score,
                matched_constraints=tuple(matched_constraints),
                reasoning=f"Matched {len(matched_constraints)} constraints and {len(overlap)} semantic keywords."
            )
            results.append((recipe, evidence))
            
    # Deterministic sort to avoid randomness
    results.sort(key=lambda x: (x[1].score, x[0].id), reverse=True)
    return results

def apply_recipe_to_plan(recipe: CinematicRecipe, plan: Any) -> None:
    """
    Outputs recommendations into existing P1 ShotPlan/MotionPlan.
    Does not execute renderer.
    """
    if not hasattr(plan, "metadata") or plan.metadata is None:
        plan.metadata = {}
    
    if "recipes" not in plan.metadata:
        plan.metadata["recipes"] = []
        
    plan.metadata["recipes"].append({
        "id": recipe.id,
        "version": recipe.version,
        "parameters": dict(recipe.parameters),
        "recommendation": recipe.prompt_recommendation
    })
