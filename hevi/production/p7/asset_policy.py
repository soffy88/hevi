"""HEVI P7.0 — The policy bridge: requirement terms -> provider allowance.

Provider authority lives in ``hevi.provider_policy``. P7 does **not** reimplement
provider state, provider selection, or the ``AVAILABLE / BLOCKED / FAILED /
NOT_ADOPTED`` model — it consumes ``ProviderDecision`` and asks one question:

    given what this requirement demands, which providers may serve it?

The answer is derived from ``ProviderDecision.eligible`` and ``.rejected``, never
from a branch on a provider name. ``if fal: ... elif pexels:`` is the anti-pattern;
every term below is a *rule about licensing and locality*, applied to whatever
providers the existing policy already decided are eligible.

Note on provider states
-----------------------
``hevi.provider_policy`` currently exposes no state enum — ``ProviderDecision``
carries eligible/rejected lists and ``selected_provider`` instead, and
``NOT_ADOPTED`` appears only in diagnostic output. Introducing an explicit
``AVAILABLE/BLOCKED/FAILED/NOT_ADOPTED`` enum is P7.1's job. This module is
written to consume either shape: it reads lists today and would read states
unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from hevi.production.p7.asset_requirement import AssetRequirement, SourcePolicy

if TYPE_CHECKING:  # pragma: no cover - typing only
    from hevi.provider_policy.policy import ProviderDecision


class Allowance(StrEnum):
    """Whether a provider may serve a requirement at all."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ProviderAllowance:
    """One provider's standing for one requirement, and why."""

    provider_id: str
    allowance: Allowance
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "allowance": self.allowance.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AssetPolicyDecision:
    """Which providers may serve this requirement, and the fallback rule."""

    requirement_id: str
    source_policy: SourcePolicy
    allowed: tuple[ProviderAllowance, ...]
    fallback: str = ""
    policy_id: str = ""

    @property
    def allowed_ids(self) -> tuple[str, ...]:
        return tuple(a.provider_id for a in self.allowed if a.allowance is Allowance.ALLOWED)

    @property
    def blocked_ids(self) -> tuple[str, ...]:
        return tuple(a.provider_id for a in self.allowed if a.allowance is Allowance.BLOCKED)

    @property
    def is_servable(self) -> bool:
        return bool(self.allowed_ids)

    def blocked_reasons(self) -> dict[str, str]:
        """Why each blocked provider is blocked, keyed by provider id.

        Carries the originating ``ProviderDecision``'s own rejection reasons through,
        so an asset-level block can always be traced to a policy-level one.
        """
        return {a.provider_id: a.reason for a in self.allowed if a.allowance is Allowance.BLOCKED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "source_policy": self.source_policy.value,
            "allowed": [a.to_dict() for a in self.allowed],
            "allowed_ids": list(self.allowed_ids),
            "blocked_ids": list(self.blocked_ids),
            "fallback": self.fallback,
            "policy_id": self.policy_id,
        }


def _locality_of(decision: ProviderDecision, provider_id: str) -> str:
    """The provider layer's declared locality, or ``UNRESOLVED``.

    P7.1 replaced ``provider_id.startswith("local")``. That made an id naming
    convention into an implicit authority: ``acme.internal-image`` — which runs
    on your own hardware — was treated as remote, and ``local-cache`` — which
    does not — was treated as local. The fact now lives in
    ``ProviderDecision.locality`` and is read, never guessed.

    An absent entry is genuinely unknown, so it is reported as unresolved rather
    than inferred from the id. Callers fail closed on it.
    """
    declared = decision.locality.get(provider_id)
    return declared.value if declared is not None else "UNRESOLVED"


def _license_of(decision: ProviderDecision, provider_id: str) -> str:
    """The provider layer's declared licence class, or ``UNRESOLVED``.

    Same principle as locality. A licence term is not derivable from where a
    provider runs — a local pipeline can fetch licensed stock, and a remote one
    can be unlicensed — so it is a declared fact too.
    """
    declared = decision.license_class.get(provider_id)
    return declared.value if declared is not None else "UNRESOLVED"


def evaluate_policy(
    requirement: AssetRequirement,
    provider_decision: ProviderDecision | None,
    *,
    policy_id: str = "",
) -> AssetPolicyDecision:
    """Apply the requirement's terms to the provider decision's eligible set."""
    policy = requirement.source_policy
    allowances: list[ProviderAllowance] = []

    if provider_decision is None:
        return AssetPolicyDecision(
            requirement_id=requirement.requirement_id,
            source_policy=policy,
            allowed=(),
            fallback="",
            policy_id=policy_id,
        )

    rejected_reasons = {
        r.provider_id: tuple(r.reasons) for r in provider_decision.rejected
    }

    for provider_id in provider_decision.eligible:
        locality = _locality_of(provider_decision, provider_id)

        if policy is SourcePolicy.LOCAL_ONLY and locality != "LOCAL":
            allowances.append(
                ProviderAllowance(
                    provider_id, Allowance.BLOCKED,
                    "LOCAL_ONLY: declared locality is "
                    f"{locality}, not LOCAL",
                )
            )
            continue

        if policy is SourcePolicy.LICENSED_ONLY:
            licence = _license_of(provider_decision, provider_id)
            if licence != "LICENSED":
                allowances.append(
                    ProviderAllowance(
                        provider_id, Allowance.BLOCKED,
                        "LICENSED_ONLY: declared licence class is "
                        f"{licence}, not LICENSED",
                    )
                )
                continue

        allowances.append(
            ProviderAllowance(
                provider_id, Allowance.ALLOWED,
                "eligible under provider policy; declared source terms satisfied",
            )
        )

    for provider_id, reasons in rejected_reasons.items():
        allowances.append(
            ProviderAllowance(
                provider_id,
                Allowance.BLOCKED,
                "provider policy rejected: " + ("; ".join(reasons) or "unspecified"),
            )
        )

    fallback = ""
    if policy in {SourcePolicy.PREFERRED_LICENSED, SourcePolicy.ANY_AVAILABLE}:
        fallback = "any eligible provider may serve this requirement"

    return AssetPolicyDecision(
        requirement_id=requirement.requirement_id,
        source_policy=policy,
        allowed=tuple(sorted(allowances, key=lambda a: a.provider_id)),
        fallback=fallback,
        policy_id=policy_id,
    )


__all__ = [
    "Allowance",
    "AssetPolicyDecision",
    "ProviderAllowance",
    "evaluate_policy",
]
