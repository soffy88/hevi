import pytest
from hevi.production.p5_3_types import CinematicRecipe, RecipeFamily, RecipeSelectionEvidence
from hevi.production.p5_3_library import RecipeLibrary
from hevi.production.p5_3_retrieval import retrieve_recipes, apply_recipe_to_plan
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class MockPlan:
    id: str
    metadata: Dict[str, Any] = None

@pytest.fixture(autouse=True)
def clean_library():
    lib = RecipeLibrary()
    lib.clear()
    yield
    lib.clear()

def test_recipe_schema_and_immutability():
    recipe = CinematicRecipe(
        id="rec_1",
        version=1,
        family=RecipeFamily.LIGHTING,
        name="Moody Blue",
        description="A moody blue lighting setup.",
        constraints=("low_light", "indoor"),
        parameters=(("intensity", 0.8),),
        prompt_recommendation="Use moody blue lighting."
    )
    assert recipe.id == "rec_1"
    
    # Test immutability via frozen dataclass
    with pytest.raises(Exception):
        recipe.name = "Changed"

def test_library_single_authority_and_versioning():
    lib = RecipeLibrary()
    recipe1 = CinematicRecipe(
        id="rec_1",
        version=1,
        family=RecipeFamily.LIGHTING,
        name="Moody Blue",
        description="A moody blue lighting setup.",
        constraints=("low_light",),
        parameters=(("intensity", 0.8),),
        prompt_recommendation="Moody blue."
    )
    lib.register(recipe1)
    
    assert lib.get("rec_1", 1) == recipe1
    
    # Same version should fail
    with pytest.raises(ValueError, match="already exists. Versions are immutable."):
        lib.register(recipe1)
        
    # Different version should succeed
    recipe2 = CinematicRecipe(
        id="rec_1",
        version=2,
        family=RecipeFamily.LIGHTING,
        name="Moody Blue V2",
        description="A moodier blue lighting setup.",
        constraints=("low_light",),
        parameters=(("intensity", 0.9),),
        prompt_recommendation="More moody blue."
    )
    lib.register(recipe2)
    assert lib.get("rec_1", 2) == recipe2

def test_semantic_constraint_retrieval():
    lib = RecipeLibrary()
    recipe1 = CinematicRecipe(
        id="rec_1", version=1, family=RecipeFamily.LIGHTING, name="Daylight",
        description="Bright daylight illumination.", constraints=("outdoor", "day"),
        parameters=(("intensity", 1.0),), prompt_recommendation="Bright daylight."
    )
    recipe2 = CinematicRecipe(
        id="rec_2", version=1, family=RecipeFamily.CAMERA, name="Tracking Shot",
        description="Tracking shot following the subject.", constraints=("motion",),
        parameters=(("speed", "medium"),), prompt_recommendation="Track subject."
    )
    lib.register(recipe1)
    lib.register(recipe2)

    # Retrieval should rank based on constraints and semantics, deterministic
    results = retrieve_recipes("bright daylight outdoor", ["outdoor", "day"])
    assert len(results) == 2
    
    top_recipe, top_evidence = results[0]
    assert top_recipe.id == "rec_1"
    assert top_evidence.score > 0
    assert "outdoor" in top_evidence.matched_constraints
    assert "day" in top_evidence.matched_constraints

    # Test family filter
    results_family = retrieve_recipes("tracking", [], family=RecipeFamily.CAMERA)
    assert len(results_family) == 1
    assert results_family[0][0].id == "rec_2"

def test_apply_recipe_to_plan():
    recipe = CinematicRecipe(
        id="rec_1", version=1, family=RecipeFamily.LIGHTING, name="Daylight",
        description="Bright daylight.", constraints=(), parameters=(("intensity", 1.0),),
        prompt_recommendation="Bright daylight."
    )
    plan = MockPlan(id="plan_1")
    apply_recipe_to_plan(recipe, plan)
    
    assert plan.metadata is not None
    assert "recipes" in plan.metadata
    assert len(plan.metadata["recipes"]) == 1
    assert plan.metadata["recipes"][0]["id"] == "rec_1"
    assert plan.metadata["recipes"][0]["parameters"] == {"intensity": 1.0}
    assert plan.metadata["recipes"][0]["recommendation"] == "Bright daylight."
    assert plan.metadata["recipes"][0]["version"] == 1
