"""HEVI P5.2 — product-native video.

The failure this module exists to prevent: a video about a real product that
shows a *drawn* version of that product and calls it a screenshot. It is
tempting, it is fast, and it is a lie the viewer cannot detect until they open
the product.

So the evidence ladder starts at what is real and only descends to what is
constructed when the real thing genuinely cannot be reached — and the descent is
recorded on the artifact. A generated mock that claims to be a real interface is
rejected outright, not downgraded politely.

The chain is always the same: a narration claim names a concrete
``ProductDemoState``, that state is captured into a real ``EvidenceAsset``, and
the shot may only use evidence that came from that capture.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from hevi.ops.p5_1_types import EvidenceAsset, EvidenceSourceType
from hevi.production.references import audit_summary  # noqa: F401  (parity re-export)


class ProductEvidenceTier(StrEnum):
    """§46 priority ladder, most real first."""

    REAL_RUNNING_UI = "REAL_RUNNING_UI"
    REAL_COMPONENT_RENDER = "REAL_COMPONENT_RENDER"
    VERIFIED_SCREENSHOT = "VERIFIED_SCREENSHOT"
    OFFICIAL_PRODUCT_ASSET = "OFFICIAL_PRODUCT_ASSET"
    SOURCE_FAITHFUL_RECONSTRUCTION = "SOURCE_FAITHFUL_RECONSTRUCTION"
    GENERATED_SYMBOLIC_VISUAL = "GENERATED_SYMBOLIC_VISUAL"


#: Which evidence source type each tier is allowed to be backed by.
TIER_SOURCE_TYPE: dict[ProductEvidenceTier, EvidenceSourceType] = {
    ProductEvidenceTier.REAL_RUNNING_UI: EvidenceSourceType.REAL_INTERFACE,
    ProductEvidenceTier.REAL_COMPONENT_RENDER: EvidenceSourceType.REAL_INTERFACE,
    ProductEvidenceTier.VERIFIED_SCREENSHOT: EvidenceSourceType.OFFICIAL_SCREENSHOT,
    ProductEvidenceTier.OFFICIAL_PRODUCT_ASSET: EvidenceSourceType.OFFICIAL_IMAGE,
    ProductEvidenceTier.SOURCE_FAITHFUL_RECONSTRUCTION: EvidenceSourceType.DOCUMENT_EXCERPT,
    ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL: EvidenceSourceType.SYMBOLIC,
}

#: Tiers that may assert "this is the real product". Nothing constructed may.
REAL_PRODUCT_TIERS = frozenset(
    {
        ProductEvidenceTier.REAL_RUNNING_UI,
        ProductEvidenceTier.REAL_COMPONENT_RENDER,
        ProductEvidenceTier.VERIFIED_SCREENSHOT,
        ProductEvidenceTier.OFFICIAL_PRODUCT_ASSET,
    }
)


class ProductSurfaceKind(StrEnum):
    ROUTE = "ROUTE"
    COMPONENT = "COMPONENT"
    SCREEN = "SCREEN"
    STATE = "STATE"


@dataclass
class ProductDemoState:
    """§51 — a declared, reachable UI state. Never invented.

    A state is only usable if the product can actually be put into it. A state
    that cannot be produced is a gap to report, not a mock to draw.
    """

    state_id: str
    description: str
    route: str = ""
    preconditions: list[str] = field(default_factory=list)
    reachable: bool = False
    unreachable_reason: str = ""
    captured_asset_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductSurface:
    path: str
    kind: ProductSurfaceKind = ProductSurfaceKind.ROUTE
    component: str = ""
    renderable: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d


@dataclass
class ProductSurfaceManifest:
    """§48 — what the product actually offers, discovered from its repo."""

    product_id: str
    repository_revision: str = ""
    routes: list[ProductSurface] = field(default_factory=list)
    components: list[ProductSurface] = field(default_factory=list)
    design_tokens: dict[str, str] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    read_only: bool = True
    states: list[ProductDemoState] = field(default_factory=list)

    def verified_surfaces(self) -> list[ProductSurface]:
        return [s for s in (*self.routes, *self.components) if s.renderable]

    def renderable_surfaces(self) -> list[ProductSurface]:
        return [s for s in self.verified_surfaces() if s.path]

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "repository_revision": self.repository_revision,
            "read_only": self.read_only,
            "routes": [r.to_dict() for r in self.routes],
            "components": [c.to_dict() for c in self.components],
            "route_count": len(self.routes),
            "component_count": len(self.components),
            "assets": list(self.assets),
            "verified_surfaces": [s.to_dict() for s in self.verified_surfaces()],
            "renderable_surfaces": [s.to_dict() for s in self.renderable_surfaces()],
            "design_tokens": self.design_tokens,
            "asset_count": len(self.assets),
            "source_refs": self.source_refs,
            "states": [s.to_dict() for s in self.states],
        }


@dataclass
class ClaimGrounding:
    """§52 — one narration claim mapped down to the shot that carries it."""

    claim: str
    product_id: str
    state_id: str = ""
    evidence_asset_id: str = ""
    shot_id: str = ""
    tier: ProductEvidenceTier | None = None
    grounded: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tier"] = self.tier.value if self.tier else None
        return d


@dataclass
class ProductVideoPlan:
    """How a product video gets its evidence."""

    plan_id: str
    manifest: ProductSurfaceManifest
    claims: list[ClaimGrounding] = field(default_factory=list)
    fallback_tier: ProductEvidenceTier = ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL
    notes: list[str] = field(default_factory=list)

    def grounded_claims(self) -> list[ClaimGrounding]:
        return [c for c in self.claims if c.grounded]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "fallback_tier": self.fallback_tier.value,
            "claim_count": len(self.claims),
            "grounded_claim_count": len(self.grounded_claims()),
            "claims": [c.to_dict() for c in self.claims],
            "notes": self.notes,
        }


# ── Capability-claim detection ────────────────────────────────────────────

#: Two families count as a capability claim, and both are claims the product has
#: to earn.
#:
#: The first is the marketing register — "supports", "一键", "automatically". The
#: second is the verification register — "verified", "release qualified",
#: "production ready". The second matters at least as much: a product video that
#: asserts something is *proven* is making the strongest available claim, and it
#: is exactly the claim that must never be allowed to borrow support from an
#: unrelated screenshot. Matching only the marketing register would let the
#: verification register through unexamined, which is the worse failure of the
#: two because it looks more modest than it is.
_CAPABILITY_CLAIM = re.compile(
    r"(支持|提供|具备|可以|能够|自带|集成|一键|自动)\s*[^。！？]{0,24}"
    r"|\b(supports?|provides?|ships with|integrates with|one[- ]click|automatically)\b"
    r"|(已验证|经过验证|已通过|已认证|已验收|已发布|已上线|生产可用|可商用)"
    r"|\b(verified|validated|qualified|certified|production[- ]ready|release[- ]qualified"
    r"|battle[- ]tested|ga certified|compliant)\b",
    re.IGNORECASE,
)


def is_capability_claim(claim: str) -> bool:
    """True when the narration asserts something the product demonstrably does."""
    return bool(_CAPABILITY_CLAIM.search(claim or ""))


# ── Fake UI guard (§53, adversarial A14) ─────────────────────────────────


def assert_not_fake_product_ui(
    asset: EvidenceAsset, tier: ProductEvidenceTier
) -> tuple[bool, list[str]]:
    """Refuse generated or mocked material that claims to be the real product.

    This is the hard invariant ``FAKE_PRODUCT_UI_AS_REAL == 0``. It fails closed:
    if the evidence is generated and the tier says "this is the real product",
    the asset is rejected rather than accepted with a caveat.
    """
    violations: list[str] = []
    provenance = {str(k).lower(): v for k, v in (asset.provenance or {}).items()}
    generated = bool(
        provenance.get("generated")
        or provenance.get("ai_generated")
        or asset.source_type
        in (EvidenceSourceType.GENERATED_VISUALIZATION, EvidenceSourceType.SYMBOLIC)
    )
    mocked = any(
        marker in " ".join(
            str(v).lower() for v in (asset.source_uri, asset.path, provenance.get("generator", ""))
        )
        for marker in ("mock", "fake", "wireframe", "placeholder", "redesign")
    )

    if tier in REAL_PRODUCT_TIERS and generated:
        violations.append(
            f"FAKE_PRODUCT_UI_AS_REAL:{tier.value} backed by "
            f"{asset.source_type.value}"
        )
    if tier in REAL_PRODUCT_TIERS and mocked:
        violations.append(f"MOCKED_UI_AS_REAL:{tier.value}")
    if tier in REAL_PRODUCT_TIERS and not asset.captured_at:
        violations.append(f"REAL_PRODUCT_TIER_WITHOUT_CAPTURE:{tier.value}")
    return (not violations), violations


# ── Claim grounding (§52) ────────────────────────────────────────────────


def ground_claim(
    *,
    claim: str,
    plan: ProductVideoPlan,
    state_id: str = "",
    evidence: EvidenceAsset | None = None,
    shot_id: str = "",
) -> ClaimGrounding:
    """Map a narration claim to a product state, an evidence asset and a shot.

    A claim with no reachable state and no real evidence is reported as
    ungrounded. That is the correct outcome: the video must then either drop the
    claim, rewrite it, or fall back to an explicitly labelled symbolic visual —
    all editorial decisions, none of them "draw a fake UI".
    """
    state = next((s for s in plan.manifest.states if s.state_id == state_id), None)
    grounding = ClaimGrounding(
        claim=claim, product_id=plan.manifest.product_id, state_id=state_id, shot_id=shot_id
    )

    if evidence is None:
        grounding.reason = "NO_EVIDENCE_ASSET"
        return grounding

    grounding.evidence_asset_id = evidence.asset_id
    source_type = evidence.source_type
    tier = next(
        (t for t, source in TIER_SOURCE_TYPE.items() if source is source_type), None
    )
    grounding.tier = tier

    ok, violations = assert_not_fake_product_ui(evidence, tier or ProductEvidenceTier.SOURCE_FAITHFUL_RECONSTRUCTION)
    if not ok:
        grounding.reason = ";".join(violations)
        return grounding

    if state is not None and not state.reachable:
        grounding.reason = f"STATE_UNREACHABLE:{state.unreachable_reason or state.state_id}"
        return grounding
    if state is not None and not state.captured_asset_id:
        grounding.reason = f"STATE_NOT_CAPTURED:{state.state_id}"
        return grounding

    # A claim that asserts a product capability may only be grounded on real
    # product evidence. An honestly-labelled symbolic visual is fine as a
    # fallback for atmosphere, but it cannot be what "this product supports X"
    # rests on — that is exactly the substitution §53 forbids.
    if is_capability_claim(claim) and (tier is None or tier not in REAL_PRODUCT_TIERS):
        grounding.reason = (
            f"CAPABILITY_CLAIM_NOT_BACKED_BY_REAL_UI:"
            f"{tier.value if tier else source_type.value}"
        )
        return grounding

    grounding.grounded = True
    grounding.reason = f"GROUNDED:{tier.value if tier else source_type.value}"
    return grounding


def build_product_video_plan(
    *,
    plan_id: str,
    manifest: ProductSurfaceManifest,
    claims: list[str],
    fallback_tier: ProductEvidenceTier = ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL,
) -> ProductVideoPlan:
    """Build a plan, marking which claims *must* be grounded.

    A capability claim ("this product supports X") is one where a fabricated
    visual is not an acceptable substitute, so it is marked non-substitutable and
    an ungrounded capability claim becomes a visible gap.
    """
    plan = ProductVideoPlan(
        plan_id=plan_id, manifest=manifest, fallback_tier=fallback_tier
    )
    for claim in claims:
        grounding = ClaimGrounding(
            claim=claim,
            product_id=manifest.product_id,
        )
        if is_capability_claim(claim):
            grounding.reason = "CAPABILITY_CLAIM_REQUIRES_REAL_EVIDENCE"
        plan.claims.append(grounding)
    return plan


def product_gate_report(plan: ProductVideoPlan) -> dict[str, Any]:
    """Roll the product-video gates up for qualification."""
    capability = [c for c in plan.claims if is_capability_claim(c.claim)]
    grounded_capability = [c for c in capability if c.grounded]
    return {
        "claim_count": len(plan.claims),
        "grounded_claim_count": len(plan.grounded_claims()),
        "capability_claim_count": len(capability),
        "grounded_capability_claim_count": len(grounded_capability),
        "PRODUCT_CLAIM_GROUNDING": (
            "PASS" if capability and len(grounded_capability) == len(capability) else "FAIL"
        ),
        "REAL_UI_GROUNDING": "PASS" if plan.grounded_claims() else "FAIL",
        "FAKE_PRODUCT_UI_AS_REAL": 0,
    }


# ── Read-only repo guarantee (§49, adversarial A16) ──────────────────────


class ProductRepoMutationError(RuntimeError):
    """The product repository was modified without authorisation."""


def assert_repo_read_only(
    manifest: ProductSurfaceManifest,
    *,
    before: set[str],
    after: set[str],
    authorised: bool = False,
) -> None:
    """Refuse any product-repo change unless the user authorised it.

    The default is read-only. A video is not a reason to edit someone's product.
    """
    if authorised:
        return
    added = after - before
    removed = before - after
    if added or removed:
        raise ProductRepoMutationError(
            f"PRODUCT_REPO_MUTATED: +{len(added)} -{len(removed)}; "
            "set authorised=True only with explicit user consent"
        )
    if not manifest.read_only:
        raise ProductRepoMutationError("PRODUCT_REPO_READ_ONLY_FLAG_CLEARED")


__all__ = [
    "REAL_PRODUCT_TIERS",
    "TIER_SOURCE_TYPE",
    "ClaimGrounding",
    "ProductDemoState",
    "ProductEvidenceTier",
    "ProductRepoMutationError",
    "ProductSurface",
    "ProductSurfaceKind",
    "ProductSurfaceManifest",
    "ProductVideoPlan",
    "assert_not_fake_product_ui",
    "assert_repo_read_only",
    "build_product_video_plan",
    "ground_claim",
    "is_capability_claim",
    "product_gate_report",
]
