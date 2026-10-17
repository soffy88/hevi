"""HEVI Director System S1 — ReferencePack + DirectorBrief data contracts.

Contract layer only: deterministic serialization/hash, explicit fail-loud
validation, pins to the existing P10a/P10b authorities. No agent, orchestrator,
semantic authority, or provider selection is introduced here (S2+ owns those).
"""

from hevi.creative.director_brief.codec import canonical_hash, canonical_json
from hevi.creative.director_brief.director_brief import (
    BRIEF_DECISION_STATES,
    PRIORITY_DIMENSIONS,
    SOURCE_TYPES,
    AntiPattern,
    ApprovalRecord,
    BriefCompleteness,
    DirectorBrief,
    Priority,
    SourceRef,
)
from hevi.creative.director_brief.errors import DirectorBriefError
from hevi.creative.director_brief.reference_pack import (
    Constraint,
    ConstraintStatus,
    Provenance,
    ReferenceEntry,
    ReferencePack,
)

__all__ = [
    "AntiPattern",
    "ApprovalRecord",
    "BRIEF_DECISION_STATES",
    "BriefCompleteness",
    "Constraint",
    "ConstraintStatus",
    "DirectorBrief",
    "DirectorBriefError",
    "PRIORITY_DIMENSIONS",
    "Priority",
    "Provenance",
    "ReferenceEntry",
    "ReferencePack",
    "SOURCE_TYPES",
    "SourceRef",
    "canonical_hash",
    "canonical_json",
]