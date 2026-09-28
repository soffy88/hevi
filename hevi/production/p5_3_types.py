from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum

class RecipeFamily(Enum):
    MOTION = "motion"
    SHOT = "shot"
    COLOR = "color"
    TIMING = "timing"

@dataclass(frozen=True)
class ParameterContract:
    name: str
    type_: str
    required: bool
    description: str
    default: Optional[Any] = None

@dataclass(frozen=True)
class Constraints:
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    required_tags: Set[str] = field(default_factory=set)
    incompatible_tags: Set[str] = field(default_factory=set)

@dataclass(frozen=True)
class CinematicRecipe:
    id: str
    version: str
    family: RecipeFamily
    name: str
    description: str
    parameters: List[ParameterContract]
    constraints: Constraints
    recommendations: Dict[str, Any]
    
    # Gates
    STRUCTURED_RECIPE_SCHEMA: bool = True
    PROMPT_ONLY_RECIPES: int = 0
    RECIPE_VERSION_IMMUTABLE: bool = True
    RENDERER_NEUTRAL_RECIPE: bool = True
    RENDERER_LOCK_IN: int = 0
    DUPLICATE_SHOT_AUTHORITY: int = 0
    DUPLICATE_MOTION_AUTHORITY: int = 0

@dataclass(frozen=True)
class RecipeSelectionEvidence:
    recipe_id: str
    recipe_version: str
    score: float
    matched_tags: List[str]
    missing_parameters: List[str]
    reasoning: str
