"""HEVI P7.0 — The bridge from compiled intent to asset requirements.

This is the layer P6 was missing. P6 completes ``ProductProductionIntent`` and
stops; nothing in it says which assets the plan needs. This derives those needs so
the existing sourcing authority can answer or refuse them.

```
ProductProductionIntent        (P6.5)
      ↓
AssetRequirement               ← this module
      ↓
hevi.sourcing                   (existing authority: discover / validate / select)
      ↓
AssetDecision                   (P7.1)
      ↓
AssetEvidence                   (P7.0 contract)
```

Nothing here fetches, downloads, ranks or selects. It produces *declarations*.

No product branching
--------------------
Requirements are derived from **capabilities** and from **grammar shapes**:

* capabilities come from P6.6's ``requirements_for(product_type)`` — an existing
  declarative table, not a branch. Reading it is the same lookup P6.6 already
  performs, and it is what makes the "capabilities differ, execution does not"
  property hold.
* grammar shapes come from ``narrative_grammar_id`` / ``presenter_grammar_id``,
  keyed the same way P6.5.1's semantic directives are keyed.

No ``product_id`` or ``commercial_product`` string appears anywhere in this module,
and a test scans for exactly that. A product is a configuration; if it needed its
own branch here, this would be a second pipeline wearing a bridge's name.

Fail-closed
-----------
An intent whose shape has no requirement rule yields no requirement rather than a
guessed one, and :func:`requirements_from_intent` refuses an intent that yields
nothing at all — because a plan needing no assets and a plan whose needs are
unknown are different states, and conflating them hides the second behind the
first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hevi.production.p6.production_runtime import Capability, requirements_for
from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_requirement import AssetRequirement

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a runtime cycle
    from hevi.production.p6.product_compiler import ProductProductionIntent


class AssetBindingError(ValueError):
    """Raised when intent cannot be turned into asset requirements."""


@dataclass(frozen=True)
class RequirementRule:
    """One rule: under this trigger, this need exists.

    Keyed by capability *or* by grammar id — never by product. A rule may declare
    a constraint set, a quantity and whether evidence is owed.
    """

    key: str
    semantic_role: AssetSemanticRole
    media_type: MediaType
    quantity: int = 1
    constraints: tuple[tuple[str, str], ...] = ()
    evidence_required: bool = True

    def to_requirement(self) -> AssetRequirement:
        return AssetRequirement(
            requirement_id=self.key,
            semantic_role=self.semantic_role,
            media_type=self.media_type,
            quantity=self.quantity,
            constraints=self.constraints,
            evidence_required=self.evidence_required,
        )


def _rule(
    key: str,
    role: AssetSemanticRole,
    kind: MediaType,
    *,
    quantity: int = 1,
    constraints: tuple[tuple[str, str], ...] = (),
    evidence_required: bool = True,
) -> RequirementRule:
    return RequirementRule(
        key=key,
        semantic_role=role,
        media_type=kind,
        quantity=quantity,
        constraints=constraints,
        evidence_required=evidence_required,
    )


# ── rules keyed by capability ───────────────────────────────────────────
# Capability-driven, so a product's needs follow from what it *requires*, not from
# what it is called. `requirements_for` already encodes the product→capability
# mapping; this encodes capability→asset.

CAPABILITY_RULES: tuple[RequirementRule, ...] = (
    _rule(
        "cap:character",
        AssetSemanticRole.CHARACTER,
        MediaType.IMAGE,
        constraints=(("face_required", "true"),),
    ),
    _rule(
        "cap:world",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
        constraints=(("aspect", "16:9"),),
    ),
    _rule(
        "cap:evidence",
        AssetSemanticRole.PROP,
        MediaType.DOCUMENT,
        evidence_required=False,
    ),
    _rule(
        "cap:document",
        AssetSemanticRole.PROP,
        MediaType.DOCUMENT,
        evidence_required=False,
    ),
    _rule(
        "cap:brand",
        AssetSemanticRole.PROP,
        MediaType.TEXTURE,
        evidence_required=False,
    ),
    _rule(
        "cap:instruction",
        AssetSemanticRole.SCENE,
        MediaType.IMAGE,
        constraints=(("aspect", "16:9"),),
    ),
    _rule(
        "cap:presenter",
        AssetSemanticRole.CHARACTER,
        MediaType.IMAGE,
        constraints=(("face_required", "true"), ("resolution", "1080"),),
    ),
    _rule(
        "cap:narrator",
        AssetSemanticRole.VOICE,
        MediaType.AUDIO,
    ),
    _rule(
        "cap:motion",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
    ),
    _rule(
        "cap:asset",
        AssetSemanticRole.PROP,
        MediaType.IMAGE,
        evidence_required=False,
    ),
)

_CAPABILITY_RULE_BY_KEY = {r.key: r for r in CAPABILITY_RULES}
_CAPABILITY_FOR_KEY = {f"cap:{c.value}": c for c in Capability}


# ── rules keyed by grammar shape ────────────────────────────────────────
# Grammar-driven, because some needs are specific to how a role performs even
# when the capabilities are generic. Keyed by grammar id — a general shape, never
# a product.

_PRESENTER_RULES: dict[str, RequirementRule] = {
    "avatar_explainer": _rule(
        "presenter:avatar_explainer",
        AssetSemanticRole.CHARACTER,
        MediaType.IMAGE,
        constraints=(("face_required", "true"), ("resolution", "1080")),
    ),
    "historical_reconstruction": _rule(
        "presenter:historical_reconstruction",
        AssetSemanticRole.CHARACTER,
        MediaType.IMAGE,
        constraints=(("face_required", "true"), ("period", "declared_by_product")),
    ),
    "documentary_explainer": _rule(
        "presenter:documentary_explainer",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
        constraints=(("duration", "4"),),
    ),
    "educational_lecture": _rule(
        "presenter:educational_lecture",
        AssetSemanticRole.CHARACTER,
        MediaType.IMAGE,
        constraints=(("face_required", "true"),),
    ),
    "product_presentation": _rule(
        "presenter:product_presentation",
        AssetSemanticRole.PROP,
        MediaType.IMAGE,
        constraints=(("resolution", "1080"),),
    ),
}

_NARRATIVE_RULES: dict[str, RequirementRule] = {
    "documentary": _rule(
        "narrative:documentary",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
        constraints=(("duration", "8"),),
    ),
    "story": _rule(
        "narrative:story",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
        constraints=(("duration", "12"),),
    ),
    "explanatory": _rule(
        "narrative:explanatory",
        AssetSemanticRole.SCENE,
        MediaType.IMAGE,
        constraints=(("aspect", "16:9"),),
        evidence_required=False,
    ),
    "short_form": _rule(
        "narrative:short_form",
        AssetSemanticRole.SCENE,
        MediaType.VIDEO,
        constraints=(("aspect", "9:16"), ("duration", "3")),
    ),
}


def requirements_from_capabilities(capabilities: frozenset[Capability]) -> tuple[AssetRequirement, ...]:
    """Capability-driven requirements, deterministically ordered."""
    return tuple(
        _CAPABILITY_RULE_BY_KEY[f"cap:{c.value}"].to_requirement()
        for c in sorted(capabilities, key=lambda c: c.value)
        if f"cap:{c.value}" in _CAPABILITY_RULE_BY_KEY
    )


def requirements_from_intent(intent: ProductProductionIntent) -> tuple[AssetRequirement, ...]:
    """Derive the asset needs of one compiled production intent.

    Fail-closed: an intent that yields no requirements raises rather than
    returning an empty tuple, because "needs nothing" and "needs are unknown" are
    different states and the second must not hide behind the first.
    """
    from hevi.production.p6.schema import ProductType

    product_type = ProductType(intent.product_type)
    declared = requirements_for(product_type)

    # Required capabilities always apply; optional ones are honoured when present
    # so a caller that supplies them gets the assets they asked for.
    wanted = set(declared.required) | set(declared.optional)
    requirements = list(requirements_from_capabilities(frozenset(wanted)))

    for grammar_id, table in (
        (intent.presenter_intent.grammar_id, _PRESENTER_RULES),
        (intent.narrative_intent.grammar_id, _NARRATIVE_RULES),
    ):
        rule = table.get(grammar_id)
        if rule is not None:
            requirements.append(rule.to_requirement())

    if not requirements:
        raise AssetBindingError(
            f"NO_ASSET_REQUIREMENTS_DERIVED:{intent.product_id}; P7 will not "
            "invent asset needs it could not derive"
        )

    # Deduplicate by requirement id, keeping first occurrence, then sort so the
    # output is content-stable regardless of rule evaluation order.
    unique = {r.requirement_id: r for r in requirements}
    return tuple(unique[k] for k in sorted(unique))


def binding_summary(requirements: tuple[AssetRequirement, ...]) -> dict[str, Any]:
    """A small, machine-readable summary for artefacts."""
    return {
        "requirement_count": len(requirements),
        "roles": sorted({r.semantic_role.value for r in requirements}),
        "media_types": sorted({r.media_type.value for r in requirements}),
        "evidence_required": sum(1 for r in requirements if r.evidence_required),
    }


__all__ = [
    "CAPABILITY_RULES",
    "AssetBindingError",
    "RequirementRule",
    "binding_summary",
    "requirements_from_capabilities",
    "requirements_from_intent",
]