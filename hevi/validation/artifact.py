"""HEVI P8.3 — Artifact validation results.

P8.3 needs to say "this artifact was validated" inside a receipt. P8.4 is where
*what* is validated gets specified — codec, resolution, duration, visual and audio
integrity — so this module defines the shape of the answer and nothing more.

The important property is that validation is a **separate, named act** rather than an
inference. A file existing on disk says bytes were written; it says nothing about
whether they are a playable video. Keeping the two apart is what lets a receipt say
"validated" and mean it.

A ``ValidationResult`` with ``passed=True`` is a claim by whoever constructed it, so
the receipt path treats a passing result as an *input to be supplied by a validator*,
never something it computes for itself. That is deliberate: the receipt's job is to
prove that validation happened, not to perform it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hevi.evidence.acquisition import checksum_bytes


class CheckOperator(StrEnum):
    """How an observation is compared against a requirement."""

    EQ = "eq"
    NE = "ne"
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"
    IN_RANGE = "in_range"
    ONE_OF = "one_of"
    NON_EMPTY = "non_empty"
    #: exactly the expected value and nothing more — used where extra audio or extra
    #: streams would itself be a defect
    EXACTLY = "exactly"

    def compare(self, observed: Any, expected: Any) -> bool:
        """Apply this operator. The only place a check can succeed."""
        if self is CheckOperator.NON_EMPTY:
            return observed not in (None, "", [], {}, ())
        if self is CheckOperator.EQ or self is CheckOperator.EXACTLY:
            return bool(observed == expected)
        if self is CheckOperator.NE:
            return bool(observed != expected)
        if self is CheckOperator.ONE_OF:
            return bool(observed in expected)
        if observed is None:
            return False
        if self is CheckOperator.IN_RANGE:
            low, high = expected
            return bool(low <= observed <= high)
        if self is CheckOperator.GTE:
            return bool(observed >= expected)
        if self is CheckOperator.GT:
            return bool(observed > expected)
        if self is CheckOperator.LTE:
            return bool(observed <= expected)
        if self is CheckOperator.LT:
            return bool(observed < expected)
        raise ValueError(f"UNHANDLED_OPERATOR:{self}")




@dataclass(frozen=True)
class ValidationCheck:
    """One named comparison, and whether it held.

    ``passed`` is **derived** from ``operator``, ``observed`` and ``expected``. It was a
    plain field in P8.3, which meant a caller could declare a verdict without anything
    having been observed. P8.4 removed that: an artifact check is a comparison, and the
    only way to satisfy one is to observe the thing and compare it.

    The comparison is a named operator from a closed set rather than an injected
    predicate, because ``lambda observed, expected: True`` is expressible and passes
    everything, while no member of :class:`CheckOperator` can.
    """

    name: str
    observed: object = None
    expected: object = None
    #: EQ by default: a check with an expectation is a comparison. Observation-only
    #: checks pass NON_EMPTY explicitly.
    operator: CheckOperator = CheckOperator.EQ
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("VALIDATION_CHECK_WITHOUT_NAME:name required")
        if not isinstance(self.operator, CheckOperator):
            raise ValueError(f"UNKNOWN_CHECK_OPERATOR:{self.operator!r}")

    @property
    def passed(self) -> bool:
        """Derived. There is no way to declare this true."""
        return bool(self.operator.compare(self.observed, self.expected))

    @property
    def was_observed(self) -> bool:
        """Whether anything was measured.

        Distinguishes "measured and wrong" from "never measured". An unobserved check
        is not a pass, which is what makes a missing probe safe.
        """
        if self.operator is CheckOperator.NON_EMPTY:
            return True
        return self.observed is not None

    def describe(self) -> str:
        seen = "not-observed" if self.observed is None else repr(self.observed)
        return f"{self.name}: observed {seen} {self.operator.value} {self.expected!r}"


@dataclass(frozen=True)
class ValidationResult:
    """The outcome of validating one artifact.

    ``passed`` is derived from the checks rather than declared, so a result cannot
    claim success while carrying a failed check. P8.4 adds concrete checks; this is
    the container they land in.
    """

    validator: str
    checks: tuple[ValidationCheck, ...] = ()
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    observed_checksum: str = ""
    #: which artifact this describes. Added in P8.4; optional so P8.3 receipts,
    #: which carry their artifact_id on the receipt itself, remain valid.
    artifact_id: str = ""

    def __post_init__(self) -> None:
        if not self.validator:
            raise ValueError("VALIDATION_RESULT_WITHOUT_VALIDATOR:validator required")
        if not self.checks:
            raise ValueError(
                "VALIDATION_RESULT_WITHOUT_CHECKS:an artifact that was never checked "
                "has not been validated"
            )
        if not isinstance(self.checks, tuple):
            raise ValueError("VALIDATION_CHECKS_MUST_BE_A_TUPLE")

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failed_checks(self) -> tuple[ValidationCheck, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def names(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks)

    def verify_payload(self, payload: bytes) -> bool:
        """Whether validation observed exactly these bytes.

        A validation result that did not hash the payload is a statement about
        something unspecified. Without this, a receipt could carry validation for one
        file and a checksum for another.
        """
        if not self.observed_checksum:
            return False
        return self.observed_checksum == checksum_bytes(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "validator": self.validator,
            "artifact_id": self.artifact_id,
            "passed": self.passed,
            "validated_at": self.validated_at.isoformat(),
            "observed_checksum": self.observed_checksum,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


__all__ = ["CheckOperator", "ValidationCheck", "ValidationResult"]
