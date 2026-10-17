from typing import Dict, List, Optional
from hevi.production.p5_3_types import CinematicRecipe, RecipeFamily

class RecipeLibrary:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RecipeLibrary, cls).__new__(cls)
            cls._instance._recipes = {}
        return cls._instance

    def register(self, recipe: CinematicRecipe):
        key = (recipe.id, recipe.version)
        if key in self._recipes:
            raise ValueError(f"Recipe version {key} already exists. Versions are immutable.")
        self._recipes[key] = recipe

    def get_all(self) -> List[CinematicRecipe]:
        return list(self._recipes.values())

    def get(self, recipe_id: str, version: int) -> Optional[CinematicRecipe]:
        return self._recipes.get((recipe_id, version))

    def clear(self):
        self._recipes.clear()
