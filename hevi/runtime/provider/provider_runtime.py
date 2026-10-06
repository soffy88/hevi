"""HEVI P8.1 — Where runtime observation sits in the chain.

The order matters, and it is the opposite of what "check the provider first" would
suggest:

    ProviderCatalogue ─▶ ProviderPolicy ─▶ ProviderDecision ─▶ Runtime Probe

The probe runs **after** policy on purpose. There is no value in asking a provider
that policy has already excluded — it costs a network round trip to learn something
already decided, and a probe of a rejected provider can produce an observation that
looks like an endorsement. So only ``ProviderDecision.eligible`` is probed.

Reachability is not eligibility. A provider can be eligible and unreachable
(``UNREACHABLE``), ineligible and reachable (``INELIGIBLE`` — never probed), or
neither (``UNKNOWN``, which is the fail-closed default). Collapsing those three is
how "the provider is down" turns into "we chose not to use it" and back again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from hevi.provider_policy.policy import ProviderDecision
from hevi.runtime.provider.models import (
    AvailabilityOutcome,
    ProviderAvailabilityDecision,
    ProviderRuntimeStatus,
)
from hevi.runtime.provider.provider_probe import ProbeFn, observe_provider


@dataclass(frozen=True)
class RuntimeObservation:
    """A whole fleet's worth of observation, plus the combined standing."""

    statuses: tuple[ProviderRuntimeStatus, ...]
    decisions: tuple[ProviderAvailabilityDecision, ...]
    checked_at: datetime

    def status_for(self, provider_id: str) -> ProviderRuntimeStatus | None:
        for status in self.statuses:
            if status.provider_id == provider_id:
                return status
        return None

    def decision_for(self, provider_id: str) -> ProviderAvailabilityDecision | None:
        for decision in self.decisions:
            if decision.provider_id == provider_id:
                return decision
        return None

    @property
    def usable_providers(self) -> tuple[str, ...]:
        return tuple(
            d.provider_id for d in self.decisions if d.outcome is AvailabilityOutcome.USABLE
        )

    @property
    def unobserved_providers(self) -> tuple[str, ...]:
        return tuple(
            s.provider_id
            for s in self.statuses
            if not s.was_probed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "statuses": [s.to_dict() for s in self.statuses],
            "decisions": [d.to_dict() for d in self.decisions],
        }


async def observe_policy_eligible(
    decision: ProviderDecision,
    *,
    probe: ProbeFn | None = None,
    checked_at: datetime | None = None,
) -> RuntimeObservation:
    """Observe only the providers policy actually allowed.

    Ineligible providers are recorded as ``INELIGIBLE`` without being probed, so the
    record still accounts for every candidate while spending no network calls on the
    ones already decided.
    """
    moment = checked_at or datetime.now(UTC)
    eligible = set(decision.eligible)

    statuses: list[ProviderRuntimeStatus] = []
    decisions: list[ProviderAvailabilityDecision] = []

    for provider_id in decision.considered:
        if provider_id not in eligible:
            decisions.append(
                ProviderAvailabilityDecision(
                    provider_id=provider_id,
                    outcome=AvailabilityOutcome.INELIGIBLE,
                    reason="provider policy did not select this provider",
                )
            )
            continue

        status = await observe_provider(provider_id, probe=probe, checked_at=moment)
        statuses.append(status)

        if status.is_usable:
            decisions.append(
                ProviderAvailabilityDecision(
                    provider_id=provider_id,
                    outcome=AvailabilityOutcome.USABLE,
                    status=status,
                    reason="eligible by policy and reachable at probe time",
                )
            )
        elif status.availability.value == "unavailable":
            decisions.append(
                ProviderAvailabilityDecision(
                    provider_id=provider_id,
                    outcome=AvailabilityOutcome.UNREACHABLE,
                    status=status,
                    reason=status.failure_reason or "provider did not answer",
                )
            )
        else:
            decisions.append(
                ProviderAvailabilityDecision(
                    provider_id=provider_id,
                    outcome=AvailabilityOutcome.UNKNOWN,
                    status=status,
                    reason=status.failure_reason or "runtime state unresolved",
                )
            )

    return RuntimeObservation(
        statuses=tuple(statuses), decisions=tuple(decisions), checked_at=moment
    )


__all__ = ["RuntimeObservation", "observe_policy_eligible"]
