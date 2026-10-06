"""HEVI P8.1 — Runtime observation models.

What a provider *is* and whether it is *working right now* are different questions
with different owners, and P7.3 froze the boundary between them:

    ProviderProfile   what it is       hevi/providers/facts.py
    ProviderDecision  what it may do   hevi/provider_policy
    ProviderRuntimeStatus  whether it answered   this module

A runtime probe reports what happened when something was asked. It does not get to
say what the provider is. ``ProviderRuntimeStatus`` therefore has no ``locality``,
no ``license_class``, no ``capabilities``, no ``quality``, and no opinion about
eligibility — a probe that answered ``locality="LOCAL"`` would be a second fact
source, which is precisely the fork P7.3 closed.

The distinction is not pedantic. Locality decides whether a provider may be used at
all under ``LOCAL_ONLY``; reachability decides whether it is answering now. Merging
them means a provider that is down looks like a provider that is prohibited, and a
provider that is remote can appear local whenever its probe times out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class RuntimeAvailability(StrEnum):
    """Whether a provider answered a probe.

    Deliberately not ``ELIGIBLE`` / ``BLOCKED``. Those answer "may this provider be
    used", which is ``ProviderPolicy``'s question and has its own vocabulary. A probe
    that emitted ``BLOCKED`` would be second-guessing eligibility it has no standing
    to judge — and would make a network outage look like a policy decision.
    """

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class AvailabilityOutcome(StrEnum):
    """Policy eligibility combined with runtime reachability.

    This is the *combination*, and it is a different object from
    ``ProviderRuntimeStatus``. Keeping them separate is what lets the two authorities
    stay independent: policy contributes eligibility, the probe contributes
    reachability, and neither learns the other's answer.

    ``UNKNOWN`` is the fail-closed default. No observation means no permission.
    """

    #: policy allowed it and it answered
    USABLE = "usable"
    #: policy allowed it, but it did not answer
    UNREACHABLE = "unreachable"
    #: policy did not allow it; it was never probed
    INELIGIBLE = "ineligible"
    #: no policy decision and no observation — fail closed
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProviderRuntimeStatus:
    """What one probe observed. An observation, never a fact.

    Fields are exactly those the P8.1 contract allows: what was asked, whether it
    answered, how long it took, when, and why it failed if it did.
    """

    provider_id: str
    availability: RuntimeAvailability = RuntimeAvailability.UNKNOWN
    reachable: bool = False
    latency_ms: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("RUNTIME_STATUS_WITHOUT_ID:provider_id required")
        if not isinstance(self.availability, RuntimeAvailability):
            raise ValueError(f"UNKNOWN_RUNTIME_AVAILABILITY:{self.availability!r}")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError(f"NEGATIVE_LATENCY:{self.latency_ms}")
        if self.availability is RuntimeAvailability.AVAILABLE and not self.reachable:
            raise ValueError(
                f"AVAILABLE_WITHOUT_REACHABLE:{self.provider_id}; a status cannot "
                "claim availability it did not observe"
            )
        if self.availability is RuntimeAvailability.UNAVAILABLE and self.failure_reason is None:
            raise ValueError(
                f"UNAVAILABLE_WITHOUT_REASON:{self.provider_id}; an unavailable "
                "provider must say why, so a network blip is distinguishable from "
                "missing configuration"
            )

    @property
    def is_usable(self) -> bool:
        """Fail-closed: only an observed, reachable provider is usable."""
        return self.availability is RuntimeAvailability.AVAILABLE and self.reachable

    @property
    def was_probed(self) -> bool:
        """Distinguishes "we asked and it failed" from "we never asked"."""
        return self.availability is not RuntimeAvailability.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "availability": self.availability.value,
            "reachable": self.reachable,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at.isoformat(),
            "failure_reason": self.failure_reason,
        }


@dataclass(frozen=True)
class ProviderAvailabilityDecision:
    """One provider's combined standing: policy eligibility + runtime reachability."""

    provider_id: str
    outcome: AvailabilityOutcome
    status: ProviderRuntimeStatus | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("AVAILABILITY_DECISION_WITHOUT_ID:provider_id required")
        if not isinstance(self.outcome, AvailabilityOutcome):
            raise ValueError(f"UNKNOWN_AVAILABILITY_OUTCOME:{self.outcome!r}")
        if self.outcome is AvailabilityOutcome.UNKNOWN and not self.reason:
            raise ValueError(
                f"UNKNOWN_AVAILABILITY_WITHOUT_REASON:{self.provider_id}; "
                "fail-closed states must be explicable"
            )

    @property
    def is_usable(self) -> bool:
        """Only USABLE passes. UNKNOWN deliberately does not."""
        return self.outcome is AvailabilityOutcome.USABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "status": self.status.to_dict() if self.status else None,
        }


__all__ = [
    "AvailabilityOutcome",
    "ProviderAvailabilityDecision",
    "ProviderRuntimeStatus",
    "RuntimeAvailability",
]
