"""HEVI P8.4 — Requirements: the *wanted* half of a check.

A check is a comparison between what was observed and what was required. This module
holds the requirement side plus the operator that joins them; the check side lives in
``hevi.validation.ValidationCheck``, which is the single check type in the codebase.

That single type is deliberate. P8.3 introduced ``ValidationCheck(name, passed)`` and
P8.4 wanted ``ArtifactCheck(name, observed, expected, passed)`` — two names for one
idea, which is the same collision P8.3 hit with ``ExecutionReceipt`` and P8.2 hit with
``AcquisitionState.FAILED``. Rather than add a second check type, P8.4 extended the
first: it now carries the observation and the expectation, and derives ``passed``.

An injected predicate would be more flexible than :class:`CheckOperator`, and much
worse. ``lambda observed, expected: True`` is expressible, and it passes everything.
An operator from a closed set cannot, and it makes the failing comparison nameable in
a failure report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.validation.artifact import CheckOperator, ValidationCheck

#: Re-exported so callers have one import for a requirement and its operator.
__all__ = ["ArtifactCheck", "CheckOperator", "CheckRequirement", "ValidationCheck"]

#: P8.4 named this "ArtifactCheck". It is the same type as ``ValidationCheck``; the
#: alias exists so P8.4 code and its documents read naturally, and it is an alias
#: rather than a subclass so there is exactly one check type at runtime.
ArtifactCheck = ValidationCheck


@dataclass(frozen=True)
class CheckRequirement:
    """What must hold, before anything has been observed.

    ``required=True`` means an unobserved check cannot pass. That is what makes a
    missing probe safe: no ffprobe means no qualification on defaults.
    """

    name: str
    expected: Any
    operator: CheckOperator = CheckOperator.EQ
    required: bool = True

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("CHECK_REQUIREMENT_WITHOUT_NAME:name required")
        if not isinstance(self.operator, CheckOperator):
            raise ValueError(f"UNKNOWN_CHECK_OPERATOR:{self.operator!r}")
