from typing import Dict, List, Optional
from hevi.production.p5_3_types import CinematicRecipe, RecipeFamily

class RecipeLibrary:
    def __init__(self):
        self._recipes: Dict[str, CinematicRecipe] = {}
        self.RECIPE_LIBRARY_SINGLE_AUTHORITY = True

    def add_recipe(self, recipe: CinematicRecipe):
        if recipe.id in self._recipes:
            raise ValueError(f"Recipe with id {recipe.id} already exists")
        self._recipes[recipe.id] = recipe

    def get_recipe(self, recipe_id: str) -> Optional[CinematicRecipe]:
        return self._recipes.get(recipe_id)

    def list_recipes(self, family: Optional[RecipeFamily] = None) -> List[CinematicRecipe]:
        if family:
            return [r for r in self._recipes.values() if r.family == family]
        return list(self._recipes.values())
