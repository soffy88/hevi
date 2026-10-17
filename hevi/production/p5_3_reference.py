from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class ReferenceVideoAnalysis:
    """Abstract analysis of a reference video."""
    video_id: str
    is_analyzed: bool = True

@dataclass
class ReferenceGrammar:
    """
    Abstract grammar extraction only.
    Captures stylistic and cinematic rules without adopting exact assets.
    """
    pacing_distribution: Dict[str, float]
    composition_families: List[str]
    camera_families: List[str]
    transition_families: List[str]
    speaker_pattern: str
    evidence_pattern: str
    information_density: float
    narrative_arc: str
    caption_behavior: str
    audio_visual_behavior: str

class AntiCopyGuard:
    """
    Enforces REFERENCE_VIDEO_COPYING=0 gate.
    Validates that a new recipe does not mechanically copy distinctive sequences.
    """
    
    @staticmethod
    def check_ordered_shot_sequence(source_shots: List[str], target_shots: List[str]) -> bool:
        """Returns True if no exact sequence match of length > 2."""
        if len(target_shots) < 3:
            return True
        target_str = ",".join(target_shots)
        for i in range(len(source_shots) - 2):
            seq = ",".join(source_shots[i:i+3])
            if seq in target_str:
                return False
        return True

    @staticmethod
    def check_timing_vector(source_timings: List[float], target_timings: List[float], tolerance: float = 0.1) -> bool:
        """Returns True if timing vectors are sufficiently different."""
        if len(source_timings) != len(target_timings):
            return True
        matches = sum(1 for s, t in zip(source_timings, target_timings) if abs(s - t) < tolerance)
        return (matches / max(1, len(source_timings))) < 0.5

    @staticmethod
    def check_asset_sequence(source_assets: List[str], target_assets: List[str]) -> bool:
        """Returns True if target doesn't reuse source asset names sequentially."""
        if not source_assets or not target_assets:
            return True
        return not any(asset in source_assets for asset in target_assets)

    @staticmethod
    def check_distinctive_sequence(source_seq: Any, target_seq: Any) -> bool:
        """Abstract guard against exact signature reproduction."""
        return source_seq != target_seq

class P5_3_Gates:
    REFERENCE_CORPUS = True
    REFERENCE_GRAMMAR = True
    REFERENCE_ABSTRACTION = True
    REFERENCE_VIDEO_COPYING = 0
    RECIPE_PROVENANCE = True
    LICENSE_BOUNDARY = True
    UNLICENSED_CODE_IMPORT = 0
    EXTERNAL_CODE_EXECUTION = 0
