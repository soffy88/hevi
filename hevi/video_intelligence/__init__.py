"""CPU-first video intelligence contracts and deterministic analysis."""

from .analysis import analyze_reel
from .boundaries import ShotBoundaryDetector, validate_boundaries
from .case_analysis import (
    ActionPhase,
    CaseAnalysis,
    PromptStructure,
    ReferenceBinding,
    TemporalComplexity,
    analyze_case,
    parse_prompt_structure,
    temporal_complexity,
)
from .case_models import (
    AssetRef,
    CaseAnalysisStatus,
    CaseIngestInput,
    CaseShot,
    DuplicateOutcome,
    PromptOrigin,
    ProvenanceRecord,
    ProvenanceStatus,
    RightsStatus,
    VideoCase,
)
from .intelligence_models import (
    BenchmarkEntry,
    BenchmarkPlan,
    CaseBenchmark,
    EvidenceType,
    IntelligenceStatus,
    PatternClusterCandidate,
    PatternLifecycle,
    ProductionLearningEvent,
    RetakeLearningRecord,
    RetakeOutcome,
    TemplateQualificationRun,
)
from .models import (
    VIDEO_INTELLIGENCE_CONTRACT_VERSION,
    ArtifactComparison,
    MotionEvidence,
    ReelAnalysis,
    ReferenceProfile,
    ShotObservation,
    VideoAsset,
    VideoProbe,
    VideoQualityReport,
)
from .motion import MotionAnalyzer
from .patterns import (
    PatternCategory,
    PatternEvidence,
    PatternStatus,
    PromptTemplate,
    VideoPattern,
    distill_prompt_template,
    extract_pattern_candidate,
    merge_pattern_evidence,
    promote_template,
    qualify_template,
)
from .probe import probe_video
from .quality import evaluate_reel_quality
from .reproduction import (
    CaseReproduction,
    ReproductionMode,
    ReproductionPlan,
    ReproductionStatus,
    build_reproduction_plan,
    reproduce_case,
)

__all__ = [
    "VIDEO_INTELLIGENCE_CONTRACT_VERSION",
    "ArtifactComparison",
    "MotionEvidence",
    "MotionAnalyzer",
    "ReferenceProfile",
    "ReelAnalysis",
    "ShotBoundaryDetector",
    "ShotObservation",
    "VideoAsset",
    "VideoProbe",
    "VideoQualityReport",
    "analyze_reel",
    "evaluate_reel_quality",
    "probe_video",
    "validate_boundaries",
    "AssetRef", "CaseAnalysisStatus", "CaseIngestInput", "CaseShot",
    "DuplicateOutcome", "PromptOrigin", "ProvenanceRecord", "ProvenanceStatus",
    "RightsStatus", "VideoCase",
    "ActionPhase", "CaseAnalysis", "PromptStructure", "ReferenceBinding",
    "TemporalComplexity", "analyze_case", "parse_prompt_structure", "temporal_complexity",
    "CaseReproduction", "ReproductionMode", "ReproductionPlan", "ReproductionStatus",
    "build_reproduction_plan", "reproduce_case",
    "PatternCategory", "PatternEvidence", "PatternStatus", "PromptTemplate", "VideoPattern",
    "distill_prompt_template", "extract_pattern_candidate", "merge_pattern_evidence",
    "promote_template", "qualify_template",
    "BenchmarkEntry", "BenchmarkPlan", "CaseBenchmark", "EvidenceType",
    "IntelligenceStatus", "PatternClusterCandidate", "PatternLifecycle",
    "ProductionLearningEvent", "RetakeLearningRecord", "RetakeOutcome",
    "TemplateQualificationRun",
]
