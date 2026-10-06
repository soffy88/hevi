"""HEVI P6 — ProductProfileCompiler contract (P6.0 architecture).

The compiler turns a :class:`~hevi.production.p6.schema.ProductProfile` into
canonical production intent that the existing runtime can consume:

    ProductProfile -> CompiledProductIntent -> existing P0-P5 runtime

Four properties are required of every implementation, and are asserted by
``tests/test_p6_0_architecture.py`` rather than trusted:

``deterministic``
    Identical profile in, byte-identical intent out. No clock, no RNG, no
    environment reads, no network. ``CompiledProductIntent.content_hash()`` is
    the check.

``fail_closed``
    An unknown product type, an unresolvable profile reference, a missing
    required grammar or a policy violation raises. There is no partial result
    and no silent default. A compiler that cannot satisfy the contract must not
    return intent.

``schema_validated``
    The profile is validated against the registry and its own composition
    invariants *before* any intent is produced.

``provider_independent``
    Compilation reads no provider and performs no provider lookup. Provider
    selection belongs to the existing provider authority; a product declares
    requirements, and the existing layer decides who can satisfy them.

P6.0 declares this contract and provides a fail-closed base. It does **not**
implement compilation: that is P6.1+ work. :class:`UnimplementedCompiler`
raises rather than returning a stub, because a stub that returns empty intent
would let a caller believe a product was compiled when nothing happened.

Composition, not branching
--------------------------
A compiler dispatches on :class:`GrammarKind` — the grammar a profile composes
— and never on :class:`ProductType`. Adding a commercial product must mean
adding a profile, never editing a conditional chain.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from hevi.production.p6.registry import GRAMMAR_REGISTRY, PRODUCT_PROFILE_REGISTRY
from hevi.production.p6.schema import GrammarKind, ProductProfile

#: Capabilities every P6 compiler must declare. Checked by the architecture
#: suite so a future compiler cannot quietly drop one.
COMPILER_CAPABILITIES: frozenset[str] = frozenset(
    {"DETERMINISTIC", "FAIL_CLOSED", "SCHEMA_VALIDATED", "PROVIDER_INDEPENDENT"}
)


class CompilerContractError(RuntimeError):
    """Raised when a compiler cannot honour the contract.

    Deliberately a ``RuntimeError`` subclass, distinct from ``ValueError``: an
    invalid profile is a ``ValueError`` at construction, whereas a compiler
    that cannot proceed is a contract breach.
    """


@dataclass(frozen=True)
class CompiledProductIntent:
    """Canonical production intent emitted by a compiler.

    This is intent, not plan. It carries no ``VisualBeat``, no ``ShotPlan``, no
    ``MotionPlan`` and no renderer: those are produced by the existing runtime
    from this intent. Holding them here would make P6 a second timeline and
    shot authority.
    """

    product_profile_id: str
    product_profile_version: str
    product_type: str
    purpose: str
    audience: str

    compiled_grammars: tuple[GrammarKind, ...] = ()
    profile_refs: tuple[str, ...] = ()
    resolved_policies: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    renderer_requirements: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_profile_id": self.product_profile_id,
            "product_profile_version": self.product_profile_version,
            "product_type": self.product_type,
            "purpose": self.purpose,
            "audience": self.audience,
            "compiled_grammars": [g.value for g in self.compiled_grammars],
            "profile_refs": list(self.profile_refs),
            "resolved_policies": list(self.resolved_policies),
            "constraints": list(self.constraints),
            "renderer_requirements": list(self.renderer_requirements),
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        """Stable hash. Equal intent must always hash equal."""
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProductProfileCompiler(ABC):
    """The single compiler contract for P6.

    Subclasses implement :meth:`compile_profile`. They must not read a
    provider, resolve a renderer, or branch on product type.
    """

    compiler_id: str = ""
    capabilities: frozenset[str] = COMPILER_CAPABILITIES

    def __init__(self) -> None:
        missing = COMPILER_CAPABILITIES - self.capabilities
        if missing:
            raise CompilerContractError(
                f"COMPILER_MISSING_CAPABILITIES:{self.compiler_id or type(self).__name__}:"
                f"{','.join(sorted(missing))}"
            )

    @abstractmethod
    def compile_profile(self, profile: ProductProfile) -> CompiledProductIntent:
        """Compile one profile into canonical production intent."""
        raise NotImplementedError

    # ── Shared validation, so no implementation can skip it ─────────────

    def validate_profile(self, profile: ProductProfile) -> None:
        """Fail closed on anything that would make compilation unsound."""
        if not isinstance(profile, ProductProfile):
            raise CompilerContractError(
                f"NOT_A_PRODUCT_PROFILE:{type(profile).__name__}"
            )
        ok, errors = profile.validate_composition()
        if not ok:
            raise CompilerContractError(
                f"INVALID_COMPOSITION:{profile.id}:{';'.join(errors)}"
            )
        for ref in profile.grammars:
            if not GRAMMAR_REGISTRY.has(ref.kind):
                raise CompilerContractError(
                    f"UNREGISTERED_GRAMMAR:{profile.id}:{ref.kind.value}"
                )
        if not profile.duration_policy:
            raise CompilerContractError(
                f"MISSING_DURATION_POLICY:{profile.id} a product must bound its duration"
            )
        if not profile.qualification_profile:
            raise CompilerContractError(
                f"MISSING_QUALIFICATION_PROFILE:{profile.id} a product must name the "
                "qualification profile it is judged against"
            )

    def compile_registered(self, profile_id: str, version: str | None = None) -> CompiledProductIntent:
        """Resolve through the registry, then compile. One lookup authority."""
        profile = PRODUCT_PROFILE_REGISTRY.get(profile_id, version)
        if profile is None:
            raise CompilerContractError(f"PRODUCT_PROFILE_NOT_FOUND:{profile_id}@{version}")
        return self.compile_profile(profile)


class UnimplementedCompiler(ProductProfileCompiler):
    """Fail-closed placeholder for P6.0.

    Exists so the contract is executable and testable before any grammar
    behaviour exists. It raises instead of returning empty intent: a caller
    that received an empty intent would reasonably believe a product had been
    compiled.
    """

    compiler_id = "p6_0_unimplemented"

    def compile_profile(self, profile: ProductProfile) -> CompiledProductIntent:
        self.validate_profile(profile)
        raise CompilerContractError(
            f"COMPILER_NOT_IMPLEMENTED:{self.compiler_id}: grammar compilation "
            "arrives in P6.1+; P6.0 declares the contract only"
        )


#: The P6.0 compiler. Fail-closed by construction.
P6_0_COMPILER = UnimplementedCompiler()


__all__ = [
    "COMPILER_CAPABILITIES",
    "P6_0_COMPILER",
    "CompiledProductIntent",
    "CompilerContractError",
    "ProductProfileCompiler",
    "UnimplementedCompiler",
]
