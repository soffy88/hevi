"""HEVI P7.0 — The asset decision record.

P5.3 has ``RecipeSelectionEvidence``; this is its asset-side counterpart. Same
purpose, same discipline: after the fact, answer *why this source* and *why not the
others*.

What this is
------------
A record. It states which source was selected, which provider decision authorised
it, how confident the choice was, and what evidence backs it.

What this is **not**
-------------------
Not a registry, repository, selector or scorer. It does not search, call a
provider, or rank. ``hevi.sourcing`` discovers, ``hevi.provider_policy`` chooses
the provider; this records what came back.

The boundary matters. A layer that both *decided* and *recorded* would sit beside
``hevi.provider_policy`` as a second selection authority, and the two would drift —
exactly the P6.2/P6.3 failure.

Provider authority is consumed, never reimplemented: :attr:`AssetDecision.
provider_decision` carries a ``hevi.provider_policy.ProviderDecision`` verbatim,
including its eligible and rejected lists, so the asset decision cannot disagree
with the provider policy that authorised it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from hevi.production.p7.evidence import AssetEvidence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hevi.provider_policy.policy import ProviderDecision

class AssetDecisionState(StrEnum):
    """The asset lifecycle: REQUESTED -> EVALUATED -> terminal.

    P7.1 added the two progression states so a decision carries its own position
    in the lifecycle, rather than only its outcome.

    What this plane deliberately does **not** own
    --------------------------------------------
    ``PRODUCED``, ``FAILED``, ``QA_PASSED``, ``BLOCKED_BY_PROVIDER`` and
    ``CANCELLED`` belong to the execution and provider layers
    (``hevi.production.p6.production_runtime.RunState``). If the asset plane could
    say "produced", a generation outcome would be assertable from a decision that
    never touched a renderer — the execution authority would have leaked back in.

    So this vocabulary and ``RunState`` are disjoint, and
    ``test_asset_plane_owns_no_execution_state`` asserts it. An ``ACCEPTED`` asset
    decision is still only an *input* to production; the proof of production is
    P6.6's ``ExecutionReceipt``.
    """

    REQUESTED = "REQUESTED"
    EVALUATED = "EVALUATED"
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"

    @property
    def is_success(self) -> bool:
        return self is AssetDecisionState.ACCEPTED

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_ASSET_STATES

    @property
    def is_provisional(self) -> bool:
        return not self.is_terminal


#: States from which no further movement happens. Defined after the enum because
#: it references its members.
_TERMINAL_ASSET_STATES = frozenset(
    {
        AssetDecisionState.ACCEPTED,
        AssetDecisionState.BLOCKED,
        AssetDecisionState.REJECTED,
    }
)


@dataclass(frozen=True)
class AssetDecision:
    """The recorded resolution of one requirement."""

    requirement_id: str
    state: AssetDecisionState
    selected_source: str = ""
    provider_decision: ProviderDecision | None = None
    confidence: float = 0.0
    evidence: tuple[AssetEvidence, ...] = ()
    policy_id: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.requirement_id:
            raise ValueError("ASSET_DECISION_WITHOUT_REQUIREMENT_ID:id required")
        if not isinstance(self.state, AssetDecisionState):
            raise ValueError(f"UNKNOWN_DECISION_STATE:{self.state!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"INVALID_CONFIDENCE:{self.confidence}; expected 0.0-1.0")

        if self.state.is_provisional:
            # A decision that has not been evaluated yet cannot be carrying a
            # selection or an authorisation; those would assert work not done.
            if self.selected_source or self.provider_decision is not None:
                raise ValueError(
                    f"PROVISIONAL_DECISION_WITH_RESULT:{self.requirement_id};"
                    f"{self.state.value} must not carry a source or provider decision"
                )
            if self.evidence:
                raise ValueError(
                    f"PROVISIONAL_DECISION_WITH_EVIDENCE:{self.requirement_id};"
                    f"{self.state.value} precedes acquisition"
                )
            return

        if self.state is AssetDecisionState.ACCEPTED:
            if not self.selected_source:
                raise ValueError(
                    f"ACCEPTED_WITHOUT_SOURCE:{self.requirement_id}; an accepted decision "
                    "must name the source it accepted"
                )
            if self.provider_decision is None:
                raise ValueError(
                    f"ACCEPTED_WITHOUT_PROVIDER_DECISION:{self.requirement_id}; provider "
                    "authority is consulted, never assumed"
                )
        else:
            if self.selected_source:
                raise ValueError(
                    f"NON_ACCEPTED_WITH_SOURCE:{self.requirement_id}; "
                    f"{self.state.value} must not name a selected source"
                )
            if not self.reason:
                raise ValueError(
                    f"NON_ACCEPTED_WITHOUT_REASON:{self.requirement_id}; "
                    f"{self.state.value} must say why"
                )

    def authorised_providers(self) -> tuple[str, ...]:
        """The provider decision's eligible list, verbatim."""
        if self.provider_decision is None:
            return ()
        return tuple(self.provider_decision.eligible)

    def blocked_providers(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """The provider decision's rejections, verbatim."""
        if self.provider_decision is None:
            return ()
        return tuple(
            (r.provider_id, tuple(r.reasons)) for r in self.provider_decision.rejected
        )

    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted(e.asset_id for e in self.evidence))

    def satisfies_evidence_policy(self, evidence_required: bool) -> bool:
        if not evidence_required:
            return True
        return bool(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        provider = self.provider_decision
        return {
            "requirement_id": self.requirement_id,
            "state": self.state.value,
            "selected_source": self.selected_source,
            "provider_decision": provider.model_dump() if provider is not None else None,
            "confidence": self.confidence,
            "evidence": [e.to_dict() for e in self.evidence],
            "policy_id": self.policy_id,
            "reason": self.reason,
        }

    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def blocked(requirement_id: str, reason: str, policy_id: str = "") -> AssetDecision:
    """Fail-closed helper. There is deliberately no ``accepted_default``."""
    return AssetDecision(
        requirement_id=requirement_id,
        state=AssetDecisionState.BLOCKED,
        policy_id=policy_id,
        reason=reason,
    )


def requested(requirement_id: str) -> AssetDecision:
    """A need declared, not yet evaluated."""
    return AssetDecision(
        requirement_id=requirement_id, state=AssetDecisionState.REQUESTED
    )


def evaluated(requirement_id: str, policy_id: str = "") -> AssetDecision:
    """Policy applied; outcome not yet recorded."""
    return AssetDecision(
        requirement_id=requirement_id,
        state=AssetDecisionState.EVALUATED,
        policy_id=policy_id,
    )


__all__ = [
    "AssetDecision",
    "AssetDecisionState",
    "blocked",
    "evaluated",
    "requested",
]
