"""HEVI P8.4 — Artifact qualification.

    artifact exists  !=  artifact valid

A descriptor records that bytes were located, which is ``FOUND`` and nothing more.
``QUALIFIED`` requires every requirement to be observed *and* satisfied. Validation
observes: the probe reads, ``qualify`` compares, and nothing in this package can write,
repair or transcode what it inspects.
"""

from hevi.artifact.checks import ArtifactCheck, CheckOperator, CheckRequirement, ValidationCheck
from hevi.artifact.qualify import (
    ArtifactDescriptor,
    ArtifactState,
    describe,
    evaluate_checks,
    qualify,
)

__all__ = [
    "ArtifactCheck",
    "ValidationCheck",
    "ArtifactDescriptor",
    "ArtifactState",
    "CheckOperator",
    "CheckRequirement",
    "describe",
    "evaluate_checks",
    "qualify",
]
