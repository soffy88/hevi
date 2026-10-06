"""HEVI P6 — registries (P6.0 architecture).

Two registries, and only two:

* :data:`PRODUCT_PROFILE_REGISTRY` — the single authority for
  :class:`~hevi.production.p6.schema.ProductProfile`. A product profile is a
  *commercial product intent*.
* :data:`GRAMMAR_REGISTRY` — the single authority mapping
  :class:`~hevi.production.p6.schema.GrammarKind` to its declared grammar
  contract.

Why this is not a second profile registry
-----------------------------------------
HEVI already has exactly one creative profile authority:
``hevi.production.p2_types.ProductionProfileRegistry``, reached through
``hevi.production.p2_profiles.get_registry()``. A ``ProductionProfile`` carries
creative direction: shot grammar, motion grammar, edit grammar, asset policy.

A ``ProductProfile`` is a different thing: it names *which commercial product
is being made* and which grammars and constraints bound it. It holds no shot
grammar, no motion grammar, no edit grammar and no asset policy, and it never
registers a ``ProductionProfile``. It refers to existing profiles by id through
``profile_refs``, which the compiler resolves against P2's registry at
runtime.

That separation is what keeps ``DUPLICATE_PROFILE_REGISTRY == 0``. It is
enforced structurally by ``tests/test_p6_0_architecture.py``, which asserts
this package defines no ``ProductionProfile`` and no
``ProductionProfileRegistry``.

Both registries are versioned and fail closed. A duplicate qualified id is a
``ValueError``, never a silent overwrite.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p6.schema import (
    CharacterGrammar,
    CinematicIntent,
    CommercialGrammar,
    DocumentaryGrammar,
    EvidenceGrammar,
    GrammarKind,
    InstructionGrammar,
    NarrativeGrammar,
    PresenterGrammar,
    ProductProfile,
    ProductType,
    ShortFormGrammar,
    WorldGrammar,
)

# ── Grammar registry ────────────────────────────────────────────────────

#: Declared grammar contract per kind. This is the composition table a compiler
#: reads; it is data, not branching logic. ``None`` means the kind carries no
#: dedicated payload object (CINEMATIC carries intent only).
GRAMMAR_CONTRACTS: dict[GrammarKind, type | None] = {
    GrammarKind.NARRATIVE: NarrativeGrammar,
    GrammarKind.PRESENTER: PresenterGrammar,
    GrammarKind.CHARACTER: CharacterGrammar,
    GrammarKind.WORLD: WorldGrammar,
    GrammarKind.EVIDENCE: EvidenceGrammar,
    GrammarKind.DOCUMENTARY: DocumentaryGrammar,
    GrammarKind.COMMERCIAL: CommercialGrammar,
    GrammarKind.INSTRUCTION: InstructionGrammar,
    GrammarKind.SHORT_FORM: ShortFormGrammar,
    GrammarKind.CINEMATIC: CinematicIntent,
}


class GrammarRegistry:
    """Single authority for grammar kinds and their declared contracts."""

    def __init__(self) -> None:
        self._contracts: dict[GrammarKind, type | None] = {}

    def register(self, kind: GrammarKind, contract: type | None) -> GrammarKind:
        if not isinstance(kind, GrammarKind):
            raise ValueError(f"UNKNOWN_GRAMMAR_KIND:{kind!r}")
        if kind in self._contracts:
            raise ValueError(f"GRAMMAR_ALREADY_REGISTERED:{kind.value}")
        if contract is not None and not isinstance(contract, type):
            raise ValueError(f"INVALID_GRAMMAR_CONTRACT:{kind.value}:{contract!r}")
        self._contracts[kind] = contract
        return kind

    def contract(self, kind: GrammarKind) -> type | None:
        return self._contracts.get(kind)

    def has(self, kind: GrammarKind) -> bool:
        return kind in self._contracts

    def list_kinds(self) -> list[GrammarKind]:
        return sorted(self._contracts, key=lambda k: k.value)

    def validate_all(self) -> tuple[bool, list[str]]:
        """Every declared grammar kind must carry a registered contract."""
        errors = [
            f"UNREGISTERED_GRAMMAR:{kind.value}"
            for kind in GrammarKind
            if kind not in self._contracts
        ]
        return (not errors), errors

    def to_dict(self) -> dict[str, Any]:
        return {
            kind.value: (contract.__name__ if contract else None)
            for kind, contract in sorted(self._contracts.items(), key=lambda kv: kv[0].value)
        }


GRAMMAR_REGISTRY = GrammarRegistry()
for _kind, _contract in GRAMMAR_CONTRACTS.items():
    GRAMMAR_REGISTRY.register(_kind, _contract)


# ── Product profile registry ────────────────────────────────────────────


class ProductProfileRegistry:
    """Single authority for commercial product intents.

    Stores :class:`ProductProfile` objects keyed ``id@version``. This is a
    product-intent registry and deliberately not a creative profile registry:
    see the module docstring.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ProductProfile] = {}
        self._versions: dict[str, list[str]] = {}

    @staticmethod
    def _key(profile_id: str, version: str) -> str:
        return f"{profile_id}@v{version}"

    def register(self, profile: ProductProfile) -> ProductProfile:
        if not isinstance(profile, ProductProfile):
            raise ValueError(f"NOT_A_PRODUCT_PROFILE:{type(profile).__name__}")
        key = self._key(profile.id, profile.version)
        if key in self._profiles:
            raise ValueError(f"PRODUCT_PROFILE_VERSION_IMMUTABLE:{key} already exists")
        ok, errors = profile.validate_composition()
        if not ok:
            raise ValueError(f"INVALID_PRODUCT_COMPOSITION:{key}:{';'.join(errors)}")
        self._profiles[key] = profile
        self._versions.setdefault(profile.id, []).append(profile.version)
        return profile

    def get(self, profile_id: str, version: str | None = None) -> ProductProfile | None:
        if version:
            return self._profiles.get(self._key(profile_id, version))
        versions = self._versions.get(profile_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=lambda v: tuple(int(p) for p in v.split(".")))[-1]
        return self._profiles.get(self._key(profile_id, latest))

    def list_profiles(self) -> list[ProductProfile]:
        return list(self._profiles.values())

    def list_ids(self) -> list[str]:
        return sorted(self._versions)

    def list_by_type(self, product_type: ProductType) -> list[ProductProfile]:
        return [p for p in self._profiles.values() if p.product_type is product_type]

    def validate(self, profile_id: str, version: str | None = None) -> tuple[bool, list[str]]:
        profile = self.get(profile_id, version)
        if profile is None:
            return False, [f"PRODUCT_PROFILE_NOT_FOUND:{profile_id}@v{version or 'latest'}"]
        errors: list[str] = []
        ok, composition_errors = profile.validate_composition()
        if not ok:
            errors.extend(composition_errors)
        declared = {g.kind for g in profile.grammars}
        errors.extend(
            f"UNREGISTERED_GRAMMAR:{kind.value}"
            for kind in declared
            if not GRAMMAR_REGISTRY.has(kind)
        )
        if profile.evidence_grammar is not None and not profile.evidence_grammar.claims:
            errors.append("EVIDENCE_GRAMMAR_WITHOUT_CLAIMS")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for profile_id in self.list_ids():
            ok, profile_errors = self.validate(profile_id)
            if not ok:
                errors.extend(f"{profile_id}:{e}" for e in profile_errors)
        return (not errors), errors

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for profile in self._profiles.values():
            by_type[profile.product_type.value] = (
                by_type.get(profile.product_type.value, 0) + 1
            )
        return {
            "total_profiles": len(self._profiles),
            "distinct_ids": len(self._versions),
            "by_product_type": dict(sorted(by_type.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {key: p.to_dict() for key, p in sorted(self._profiles.items())}


PRODUCT_PROFILE_REGISTRY = ProductProfileRegistry()


__all__ = [
    "GRAMMAR_CONTRACTS",
    "GRAMMAR_REGISTRY",
    "PRODUCT_PROFILE_REGISTRY",
    "GrammarRegistry",
    "ProductProfileRegistry",
]
