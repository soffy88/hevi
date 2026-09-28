from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from enum import Enum

class RecipeFamily(Enum):
    LIGHTING = "lighting"
    CAMERA = "camera"
    COLOR_GRADE = "color_grade"
    TRANSITION = "transition"
    COMPOSITION = "composition"
    MOTION = "motion"

@dataclass(frozen=True)
class CinematicRecipe:
    id: str
    version: int
    family: RecipeFamily
    name: str
    description: str
    constraints: tuple[str, ...]
    parameters: tuple[tuple[str, Any], ...]
    prompt_recommendation: str

@dataclass(frozen=True)
class RecipeSelectionEvidence:
    recipe_id: str
    score: float
    matched_constraints: tuple[str, ...]
    reasoning: str
