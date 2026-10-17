"""HEVI validation — artifact validation results.

P8.3 defines the container; P8.4 fills in codec, resolution, duration and
visual/audio integrity checks.
"""

from hevi.validation.artifact import ValidationCheck, ValidationResult
from hevi.validation.layout_gate import (
    Box,
    LayoutAuditReport,
    audit_sampled_frames,
    check_clipped,
    check_safe_area,
    compute_overlap_ratio,
)

__all__ = [
    "Box",
    "LayoutAuditReport",
    "ValidationCheck",
    "ValidationResult",
    "audit_sampled_frames",
    "check_clipped",
    "check_safe_area",
    "compute_overlap_ratio",
]
