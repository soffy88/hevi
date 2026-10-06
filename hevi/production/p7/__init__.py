"""HEVI P7 — Production execution: intent drives assets, providers, render, audio.

P7 owns **no** asset or provider authority. Both already exist:

* ``hevi.sourcing`` — asset acquisition, validation, selection, matching
* ``hevi.providers`` / ``hevi.provider_policy`` — provider registration and policy
* ``hevi.production.p0_pipeline`` — ``ShotPlan``, ``MotionPlan``, ``AudioLock``
* ``hevi.production.p6.production_runtime`` — ``ExecutionReceipt``

What P7 adds is the missing layer between them: the vocabulary that lets a
compiled P6 intent state what assets it needs, and the decision record of how a
need resolved against a provider's *declared* facts. Everything P7 records is
auditable; nothing P7 acquires.

Asset lifecycle lives here; execution lifecycle does not. ``AssetDecisionState``
and ``RunState`` are disjoint by construction — an ``ACCEPTED`` asset decision is an
input to production, never a claim that production happened. Only
``ExecutionReceipt`` can say that.

Layout, matching the corrected P7 scope:

* ``asset_contract``  — ``MediaType``, ``AssetSemanticRole``, ``AssetOrigin``,
  ``AssetStatus``, ``AssetReference`` (the vocabulary; sourcing's role taxonomy is
  reused verbatim, and ``MediaType`` is deliberately disjoint from it)
* ``asset_requirement`` — ``AssetRequirement``: a declared need
* ``asset_policy``    — reads ``ProviderDecision`` facts; decides terms, never
  eligibility, and never infers a fact from a provider id
* ``asset_decision``  — ``AssetDecision`` + ``AssetDecisionState``: the record of how
  a need resolved, and the asset lifecycle
* ``asset_intelligence`` — ``AssetDecisionAuthority``: the single decision entry point
* ``evidence``        — ``AssetEvidence``: proof an asset really exists
* ``asset_binding``   — P6 intent -> requirements, keyed by capability and grammar

``NO_SECOND_ASSET_AUTHORITY`` forbids ``AssetManager`` / ``AssetStore`` /
``NewAssetRepository`` / ``AssetRegistry`` in this package, and permits
``hevi.sourcing.AssetRepository`` as the existing owner.
"""

from __future__ import annotations

from hevi.production.p7.asset_binding import (
    AssetBindingError,
    RequirementRule,
    binding_summary,
    requirements_from_capabilities,
    requirements_from_intent,
)
from hevi.production.p7.asset_contract import (
    SOURCING_ASSET_TYPES,
    AssetOrigin,
    AssetReference,
    AssetSemanticRole,
    AssetStatus,
    MediaType,
)
from hevi.production.p7.asset_decision import (
    AssetDecision,
    AssetDecisionState,
    blocked,
    evaluated,
    requested,
)
from hevi.production.p7.asset_intelligence import (
    AssetDecisionAuthority,
    AssetIntelligenceError,
    AssetResolution,
)
from hevi.production.p7.asset_policy import (
    Allowance,
    AssetPolicyDecision,
    ProviderAllowance,
    evaluate_policy,
)
from hevi.production.p7.asset_requirement import (
    KNOWN_CONSTRAINTS,
    AssetRequirement,
    SourcePolicy,
)
from hevi.production.p7.evidence import AssetEvidence

__all__ = [
    "SOURCING_ASSET_TYPES",
    "AssetBindingError",
    "AssetDecision",
    "AssetEvidence",
    "AssetOrigin",
    "AssetReference",
    "AssetRequirement",
    "AssetSemanticRole",
    "AssetStatus",
    "Allowance",
    "AssetDecisionAuthority",
    "AssetDecisionState",
    "AssetIntelligenceError",
    "AssetPolicyDecision",
    "AssetResolution",
    "KNOWN_CONSTRAINTS",
    "MediaType",
    "ProviderAllowance",
    "SourcePolicy",
    "evaluate_policy",
    "RequirementRule",
    "blocked",
    "evaluated",
    "requested",
    "binding_summary",
    "requirements_from_capabilities",
    "requirements_from_intent",
]
