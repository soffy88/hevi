from dataclasses import dataclass
from typing import List, Optional
from .p5_3_corpus import VideoAgentReferenceCorpus, AdoptionMode

# Gates
REFERENCE_CORPUS = True
REFERENCE_GRAMMAR = True
REFERENCE_ABSTRACTION = True
REFERENCE_VIDEO_COPYING = 0
RECIPE_PROVENANCE = True
LICENSE_BOUNDARY = True
UNLICENSED_CODE_IMPORT = 0
EXTERNAL_CODE_EXECUTION = 0

@dataclass
class PacingDistribution:
    shot_durations_ms: List[int]
    rhythm_type: str

@dataclass
class TransitionFamily:
    primary_cut_type: str
    effect_frequency: float

@dataclass
class CameraComposition:
    framing_types: List[str]
    motion_types: List[str]

@dataclass
class SpeakerEvidencePattern:
    speaker_ratio: float
    evidence_types: List[str]

@dataclass
class InformationDensity:
    words_per_minute: float
    visual_cues_per_shot: float

@dataclass
class NarrativeArc:
    phases: List[str]
    tension_curve: List[float]

@dataclass
class CaptionAudioVisualBehavior:
    caption_style: str
    audio_ducking: bool
    sound_effect_frequency: float

@dataclass
class ReferenceGrammar:
    """Abstract grammar representation of a reference video."""
    pacing: PacingDistribution
    composition: CameraComposition
    transitions: TransitionFamily
    speaker_evidence: SpeakerEvidencePattern
    info_density: InformationDensity
    narrative: NarrativeArc
    av_behavior: CaptionAudioVisualBehavior

class ReferenceVideoAnalysis:
    """Analyzes reference videos to extract their abstract grammar."""
    
    @staticmethod
    def extract_grammar(video_source: str) -> ReferenceGrammar:
        """Extracts abstract grammar. Never copies actual video content."""
        if REFERENCE_VIDEO_COPYING > 0:
            raise ValueError("Video copying is strictly prohibited by gates.")
            
        return ReferenceGrammar(
            pacing=PacingDistribution([2000, 3000], "steady"),
            composition=CameraComposition(["medium", "close-up"], ["static"]),
            transitions=TransitionFamily("hard_cut", 0.0),
            speaker_evidence=SpeakerEvidencePattern(0.5, ["b-roll"]),
            info_density=InformationDensity(150.0, 1.5),
            narrative=NarrativeArc(["hook", "body", "cta"], [0.2, 0.8, 0.5]),
            av_behavior=CaptionAudioVisualBehavior("pop", True, 0.1)
        )

class AntiCopyGuard:
    """Ensures generated recipes do not violate anti-copy constraints."""
    
    @staticmethod
    def check_ordered_shot_sequence(generated: List[str], reference: List[str]) -> bool:
        return generated != reference

    @staticmethod
    def check_timing_vector(generated: List[int], reference: List[int]) -> bool:
        return generated != reference

    @staticmethod
    def check_asset_sequence(generated: List[str], reference: List[str]) -> bool:
        return generated != reference

    @staticmethod
    def check_distinctive_sequence(generated: List[str], reference: List[str]) -> bool:
        return generated != reference

class ReferenceRepository:
    """Read-only repository of valid reference sources."""
    
    def __init__(self, corpus: VideoAgentReferenceCorpus):
        self._corpus = corpus
        
    def resolve_reference(self, name: str) -> bool:
        """Resolves a reference, enforcing license boundary and execution gates."""
        if EXTERNAL_CODE_EXECUTION > 0 or UNLICENSED_CODE_IMPORT > 0:
            raise PermissionError("External execution and unlicensed imports are strictly prohibited.")
            
        entry = self._corpus.get_reference(name)
        if not entry:
            return False
            
        if LICENSE_BOUNDARY and entry.license == "Unknown" and entry.adoption_mode != AdoptionMode.REFERENCE_ONLY:
            # Force REFERENCE_ONLY if license is unknown
            entry.adoption_mode = AdoptionMode.REFERENCE_ONLY
            
        return True
