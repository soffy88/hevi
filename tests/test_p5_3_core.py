import pytest
from hevi.production.p5_3_types import (
    CinematicRecipe, RecipeFamily, ParameterContract, Constraints
)
from hevi.production.p5_3_library import RecipeLibrary
from hevi.production.p5_3_retrieval import RecipeRetrieval
import dataclasses

def test_recipe_immutability():
    recipe = CinematicRecipe(
        id="r1",
        version="1.0",
        family=RecipeFamily.MOTION,
        name="Test",
        description="Test desc",
        parameters=[],
        constraints=Constraints(),
        recommendations={}
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        recipe.name = "Mutated"

def test_library_single_authority():
    lib = RecipeLibrary()
    recipe = CinematicRecipe(
        id="r1",
        version="1.0",
        family=RecipeFamily.MOTION,
        name="Test",
        description="Test desc",
        parameters=[],
        constraints=Constraints(),
        recommendations={}
    )
    lib.add_recipe(recipe)
    assert lib.get_recipe("r1") == recipe
    with pytest.raises(ValueError):
        lib.add_recipe(recipe)

def test_retrieval_constraints():
    lib = RecipeLibrary()
    recipe = CinematicRecipe(
        id="r1",
        version="1.0",
        family=RecipeFamily.MOTION,
        name="Pan",
        description="Slow pan",
        parameters=[],
        constraints=Constraints(required_tags={"slow"}),
        recommendations={}
    )
    lib.add_recipe(recipe)
    retrieval = RecipeRetrieval(lib)
    
    # Fails constraint
    results = retrieval.retrieve("pan", context={}, tags={"fast"})
    assert len(results) == 0
    
    # Passes constraint
    results = retrieval.retrieve("pan", context={}, tags={"slow"})
    assert len(results) == 1
    assert results[0].recipe_id == "r1"

def test_gates_present():
    recipe = CinematicRecipe(
        id="dummy", version="1", family=RecipeFamily.MOTION,
        name="n", description="d", parameters=[], constraints=Constraints(), recommendations={}
    )
    assert recipe.STRUCTURED_RECIPE_SCHEMA is True
    assert recipe.PROMPT_ONLY_RECIPES == 0
    assert recipe.RECIPE_VERSION_IMMUTABLE is True
    assert recipe.RENDERER_NEUTRAL_RECIPE is True
    assert recipe.RENDERER_LOCK_IN == 0
    assert recipe.DUPLICATE_SHOT_AUTHORITY == 0
    assert recipe.DUPLICATE_MOTION_AUTHORITY == 0
    
    lib = RecipeLibrary()
    assert lib.RECIPE_LIBRARY_SINGLE_AUTHORITY is True
    
    retrieval = RecipeRetrieval(lib)
    assert retrieval.SEMANTIC_RECIPE_RETRIEVAL is True
    assert retrieval.CONSTRAINT_AWARE_RETRIEVAL is True
    assert retrieval.RANDOM_SELECTION == 0
    assert retrieval.RECIPE_SELECTION_TRACEABLE is True
    assert retrieval.RECIPE_PARAMETERIZATION is True
