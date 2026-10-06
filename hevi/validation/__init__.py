"""HEVI validation — artifact validation results.

P8.3 defines the container; P8.4 fills in codec, resolution, duration and
visual/audio integrity checks.
"""

from hevi.validation.artifact import ValidationCheck, ValidationResult

__all__ = ["ValidationCheck", "ValidationResult"]
