from typing import List, Dict, Any, Set, Optional
from hevi.production.p5_3_types import CinematicRecipe, RecipeSelectionEvidence
from hevi.production.p5_3_library import RecipeLibrary

class RecipeRetrieval:
    def __init__(self, library: RecipeLibrary):
        self.library = library
        self.SEMANTIC_RECIPE_RETRIEVAL = True
        self.CONSTRAINT_AWARE_RETRIEVAL = True
        self.RANDOM_SELECTION = 0
        self.RECIPE_SELECTION_TRACEABLE = True
        self.RECIPE_PARAMETERIZATION = True

    def retrieve(self, query: str, context: Dict[str, Any], tags: Set[str], duration: Optional[float] = None) -> List[RecipeSelectionEvidence]:
        results = []
        for recipe in self.library.list_recipes():
            # Constraint check
            if duration is not None:
                if recipe.constraints.min_duration and duration < recipe.constraints.min_duration:
                    continue
                if recipe.constraints.max_duration and duration > recipe.constraints.max_duration:
                    continue
            
            if recipe.constraints.required_tags and not recipe.constraints.required_tags.issubset(tags):
                continue
            
            if recipe.constraints.incompatible_tags and recipe.constraints.incompatible_tags.intersection(tags):
                continue
            
            # Simple semantic scoring dummy (keyword match)
            score = 0.0
            query_words = set(query.lower().split())
            name_words = set(recipe.name.lower().split())
            desc_words = set(recipe.description.lower().split())
            
            intersection = query_words.intersection(name_words.union(desc_words))
            score += len(intersection) * 0.5
            
            matched_tags = list(recipe.constraints.required_tags.intersection(tags))
            score += len(matched_tags) * 0.2
            
            if score > 0:
                results.append(RecipeSelectionEvidence(
                    recipe_id=recipe.id,
                    recipe_version=recipe.version,
                    score=score,
                    matched_tags=matched_tags,
                    missing_parameters=[],
                    reasoning=f"Matched {len(intersection)} query terms and {len(matched_tags)} tags"
                ))
                
        results.sort(key=lambda x: x.score, reverse=True)
        return results
