"""Canonical, renderer-independent shot intelligence.

The package is deliberately planning-only.  It does not call a renderer or
provider and is disabled unless ``SHOT_INTELLIGENCE_ENABLED=1``.
"""

from hevi.cinematic.shot_intelligence.models import (
    AestheticProfile,
    BeatCue,
    CameraMotion,
    Composition,
    ShotIntent,
    ShotPlan,
    ShotRecipe,
    ShotSelectionResult,
    TransitionIntent,
)
from hevi.cinematic.shot_intelligence.selector import ShotSelector
from hevi.cinematic.shot_intelligence.sequence import SequencePlanner
from hevi.cinematic.shot_intelligence.validator import VisualQAResult, validate_shot_plan

__all__ = [
    "AestheticProfile", "BeatCue", "CameraMotion", "Composition", "ShotIntent",
    "ShotPlan", "ShotRecipe", "ShotSelectionResult", "TransitionIntent",
    "ShotSelector", "SequencePlanner", "VisualQAResult", "validate_shot_plan",
]
