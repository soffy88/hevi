"""HEVI P7.0 — The asset decision authority.

```
ProductIntent        (P6.5)
      ↓
AssetRequirement     (asset_binding)
      ↓
AssetDecisionAuthority      ← this module
      ├── AssetRequirement
      ├── AssetPolicy            → hevi.provider_policy.ProviderDecision
      ├── hevi.sourcing          → discover / validate
      ↓
AssetDecision  +  AssetEvidence
```

This is a **decision** authority, not a store and not an acquisition authority. It
orchestrates the existing layers and records what they decided; it acquires,
downloads, ranks and stores nothing.

Why "authority" and not "service"
---------------------------------
It is the single place where "which asset serves this requirement, and on whose
authority" is settled and recorded. Naming it *service* or *manager* would have
made it a candidate second owner, and the whole point is that it is not: every
substantive judgement belongs to ``hevi.provider_policy`` (providers) or
``hevi.sourcing`` (assets), and this only carries their answers together.

Fail-closed
-----------
* No provider decision -> ``BLOCKED``, never a default source.
* No eligible provider -> ``BLOCKED``, never a silent substitution.
* Evidence demanded but absent -> the decision is returned as ``BLOCKED`` rather
  than ``ACCEPTED``, because an unevidenced acceptance is indistinguishable from
  fabrication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hevi.production.p7.asset_decision import (
    AssetDecision,
    AssetDecisionState,
)
from hevi.production.p7.asset_policy import AssetPolicyDecision, evaluate_policy
from hevi.production.p7.asset_requirement import AssetRequirement
from hevi.production.p7.evidence import AssetEvidence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hevi.provider_policy.policy import ProviderDecision


class AssetIntelligenceError(RuntimeError):
    """Raised when a decision cannot be produced at all."""


@dataclass(frozen=True)
class AssetResolution:
    """A requirement together with everything decided about it."""

    requirement: AssetRequirement
    policy: AssetPolicyDecision
    decision: AssetDecision

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "policy": self.policy.to_dict(),
            "decision": self.decision.to_dict(),
        }


class AssetDecisionAuthority:
    """The single asset decision authority.

    Stateless. Every call returns a complete :class:`AssetResolution`; nothing is
    cached, so one requirement's resolution cannot leak into another's.
    """

    authority_id = "p7_0_asset_decision"

    def decide(
        self,
        requirement: AssetRequirement,
        *,
        provider_decision: ProviderDecision | None,
        selected_source: str = "",
        confidence: float = 0.0,
        evidence: tuple[AssetEvidence, ...] = (),
        policy_id: str = "",
    ) -> AssetResolution:
        """Decide one requirement. Fails closed at every step."""
        policy = evaluate_policy(requirement, provider_decision, policy_id=policy_id)

        if provider_decision is None:
            return self._blocked(
                requirement, policy, "NO_PROVIDER_DECISION:provider authority not consulted"
            )
        if not policy.is_servable:
            blocked_ids = ",".join(policy.blocked_ids) or "none"
            return self._blocked(
                requirement,
                policy,
                f"NO_ELIGIBLE_PROVIDER:source_policy={requirement.source_policy.value}:"
                f"blocked={blocked_ids}",
            )
        if provider_decision.selected_provider and not selected_source:
            # The provider policy chose a provider but nothing has been acquired
            # yet. Naming it as the source would assert an acquisition that did not
            # happen, so this is blocked until evidence exists.
            return self._blocked(
                requirement,
                policy,
                "NO_ASSET_OBTAINED:provider selected but no source acquired; evidence "
                "is required before a decision can claim acceptance",
            )

        if requirement.evidence_required and not evidence:
            return self._blocked(
                requirement, policy, "NO_ASSET_EVIDENCE:requirement demands evidence"
            )

        decision = AssetDecision(
            requirement_id=requirement.requirement_id,
            state=AssetDecisionState.ACCEPTED,
            selected_source=selected_source,
            provider_decision=provider_decision,
            confidence=confidence,
            evidence=evidence,
            policy_id=policy_id,
        )
        return AssetResolution(requirement=requirement, policy=policy, decision=decision)

    @staticmethod
    def _blocked(
        requirement: AssetRequirement,
        policy: AssetPolicyDecision,
        reason: str,
    ) -> AssetResolution:
        return AssetResolution(
            requirement=requirement,
            policy=policy,
            decision=AssetDecision(
                requirement_id=requirement.requirement_id,
                state=AssetDecisionState.BLOCKED,
                policy_id=policy.policy_id,
                reason=reason,
            ),
        )

    def decide_all(
        self,
        requirements: tuple[AssetRequirement, ...],
        **kwargs: Any,
    ) -> tuple[AssetResolution, ...]:
        """Decide every requirement, in the order given."""
        return tuple(self.decide(r, **kwargs) for r in requirements)

    def blocked_summary(self, resolutions: tuple[AssetResolution, ...]) -> dict[str, Any]:
        """Machine-readable view of what could not be served."""
        blocked = [r for r in resolutions if r.decision.state is AssetDecisionState.BLOCKED]
        return {
            "total": len(resolutions),
            "blocked": len(blocked),
            "blocked_requirements": {r.requirement.requirement_id: r.decision.reason for r in blocked},
            "any_available": any(r.decision.state.is_success for r in resolutions),
        }


__all__ = ["AssetDecisionAuthority", "AssetIntelligenceError", "AssetResolution"]
