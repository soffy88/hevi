"""HEVI P6.1 — Narrative compiler.

Compiles ``ProductProfile`` + ``NarrativeGrammar`` into a ``NarrativeIntent``.

    ProductProfile.narrative_grammar_id
        -> NARRATIVE_GRAMMAR_REGISTRY.resolve()
        -> NarrativeCompiler.compile()
        -> NarrativeIntent

Three properties, each verified by an executing test rather than asserted:

``deterministic``
    Identical inputs produce a byte-identical intent, including
    ``content_hash()``. Node order comes from the grammar's declared ``order``
    field, which P6.1 requires to be unique, so there is nothing to sort
    ambiguously and no clock, RNG or environment read anywhere in the path.

``fail_closed``
    An unknown grammar id, a profile with no narrative grammar, a grammar whose
    required nodes were all dropped, or a constraint violation raises. There is
    no partial intent and no silent default — an intent missing its required
    nodes would ship a video with a hole in its structure.

``serializable``
    ``to_dict()`` round-trips through JSON with sorted keys, and the hash is
    derived from that same payload.

Not an authority
----------------
The compiler emits *narrative intent*: an ordered node sequence with its
constraints. It does not emit ``VisualBeat``, ``ShotPlan``, ``MotionPlan``, or a
renderer, and it performs no cut. Those belong to P1, P0 and P5.2 respectively.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hevi.production.p6.narrative.model import NarrativeGrammar, NarrativeNode
from hevi.production.p6.narrative.registry import (
    NARRATIVE_GRAMMAR_REGISTRY,
    NarrativeGrammarRegistry,
)
from hevi.production.p6.schema import ProductConstraint, ProductProfile


class NarrativeCompilationError(ValueError):
    """Raised when a narrative intent cannot be produced.

    A ``ValueError`` because the cause is a defect in the profile or grammar,
    not a runtime fault.
    """


@dataclass(frozen=True)
class NarrativeValidationResult:
    """What compilation checked, and what it concluded.

    Recorded on the intent so a later stage can see that validation ran rather
    than inferring it from the presence of an intent.
    """

    valid: bool
    checked: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "checked": list(self.checked),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class NarrativeIntent:
    """Compiled narrative intent for one product.

    Holds an ordered node sequence and its constraints. Deliberately holds no
    timeline, shot, or motion object: this is what the existing runtime consumes,
    not a replacement for it.
    """

    grammar_id: str
    grammar_version: str
    product_profile_id: str
    nodes: tuple[NarrativeNode, ...] = ()
    sequence: tuple[str, ...] = ()
    constraints: tuple[ProductConstraint, ...] = ()
    validation_result: NarrativeValidationResult = field(
        default_factory=lambda: NarrativeValidationResult(valid=False)
    )
    excluded_optional_nodes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "grammar_id": self.grammar_id,
            "grammar_version": self.grammar_version,
            "product_profile_id": self.product_profile_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "sequence": list(self.sequence),
            "constraints": [c.to_dict() for c in self.constraints],
            "validation_result": self.validation_result.to_dict(),
            "excluded_optional_nodes": list(self.excluded_optional_nodes),
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.nodes)


class NarrativeCompiler:
    """Compiles a product profile's narrative grammar into intent.

    Stateless and reusable. Holds no per-compile state, so the same instance
    compiles any number of profiles identically.
    """

    compiler_id = "p6_1_narrative"

    def __init__(self, registry: NarrativeGrammarRegistry | None = None) -> None:
        # Default to the single module-level authority. Injecting a registry is
        # for tests needing isolation; production uses the one registry.
        self._registry = registry if registry is not None else NARRATIVE_GRAMMAR_REGISTRY

    @property
    def registry(self) -> NarrativeGrammarRegistry:
        return self._registry

    def resolve_grammar(self, profile: ProductProfile) -> NarrativeGrammar:
        """Resolve the profile's declared grammar, or fail closed."""
        if not isinstance(profile, ProductProfile):
            raise NarrativeCompilationError(
                f"NOT_A_PRODUCT_PROFILE:{type(profile).__name__}"
            )
        grammar_id = profile.narrative_grammar_id
        if not grammar_id:
            raise NarrativeCompilationError(
                f"MISSING_NARRATIVE_GRAMMAR_ID:{profile.id} declares no narrative grammar"
            )
        grammar, version = _split_qualified(grammar_id)
        try:
            return self._registry.resolve(grammar, version)
        except KeyError as exc:
            raise NarrativeCompilationError(
                f"UNKNOWN_NARRATIVE_GRAMMAR:{grammar_id}"
            ) from exc

    def compile(self, profile: ProductProfile) -> NarrativeIntent:
        """Compile one profile into narrative intent.

        Optional nodes are included. A profile that wants a shorter arc excludes
        them through :meth:`compile_with`, which is how the same grammar serves
        both a 20-second cut and a three-minute one.
        """
        return self.compile_with(profile)

    def compile_with(
        self,
        profile: ProductProfile,
        *,
        include_optional: bool = True,
        extra_constraints: tuple[ProductConstraint, ...] = (),
    ) -> NarrativeIntent:
        """Compile with explicit control over optional nodes and constraints."""
        grammar = self.resolve_grammar(profile)

        # A grammar's own constraints bound the shape it describes, so they are
        # carried onto the intent as well as enforced during validation. Without
        # this a consumer of the intent could not see why a node was required.
        effective_constraints = _merge_constraints(
            profile.constraints, grammar.constraints, extra_constraints
        )

        ordered = grammar.ordered_nodes()
        selected: list[NarrativeNode] = []
        excluded: list[str] = []
        for node in ordered:
            if node.optional and not include_optional:
                excluded.append(node.id)
                continue
            selected.append(node)

        validation = self._validate(grammar, selected, excluded, effective_constraints)
        if not validation.valid:
            raise NarrativeCompilationError(
                f"NARRATIVE_VALIDATION_FAILED:{profile.id}:{';'.join(validation.errors)}"
            )

        return NarrativeIntent(
            grammar_id=grammar.id,
            grammar_version=grammar.version,
            product_profile_id=profile.id,
            nodes=tuple(selected),
            sequence=tuple(n.type.value for n in selected),
            constraints=effective_constraints,
            validation_result=validation,
            excluded_optional_nodes=tuple(excluded),
        )

    # ── Validation ──────────────────────────────────────────────────────

    def _validate(
        self,
        grammar: NarrativeGrammar,
        selected: list[NarrativeNode],
        excluded: list[str],
        effective_constraints: tuple[ProductConstraint, ...],
    ) -> NarrativeValidationResult:
        checked: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []

        checked.append("non_empty_sequence")
        if not selected:
            errors.append("EMPTY_NARRATIVE_SEQUENCE")
            return NarrativeValidationResult(False, tuple(checked), tuple(errors), tuple(warnings))

        checked.append("required_nodes_present")
        selected_ids = {n.id for n in selected}
        missing = [nid for nid in grammar.required_node_ids() if nid not in selected_ids]
        if missing:
            errors.append(f"REQUIRED_NODES_EXCLUDED:{','.join(sorted(missing))}")

        checked.append("grammar_constraints")
        for constraint in effective_constraints:
            if constraint.key == "min_nodes" and constraint.value.isdigit():
                minimum = int(constraint.value)
                if len(selected) < minimum:
                    errors.append(
                        f"MIN_NODES_VIOLATED:{len(selected)}<{minimum}"
                    )
            elif constraint.key == "demonstration_required" and constraint.value == "true":
                if not any(n.type.value == "DEMONSTRATION" for n in selected):
                    errors.append("DEMONSTRATION_REQUIRED_BUT_ABSENT")
            elif constraint.key == "evidence_before_interpretation" and constraint.value == "true":
                order = {n.type.value: i for i, n in enumerate(selected)}
                if (
                    "EVIDENCE" in order
                    and "INTERPRETATION" in order
                    and order["EVIDENCE"] > order["INTERPRETATION"]
                ):
                    errors.append("EVIDENCE_AFTER_INTERPRETATION")
            elif constraint.key == "conflict_required" and constraint.value == "true":
                if not any(n.type.value == "CONFLICT" for n in selected):
                    errors.append("CONFLICT_REQUIRED_BUT_ABSENT")
            elif constraint.key == "turning_point_required" and constraint.value == "true":
                if not any(n.type.value == "TURNING_POINT" for n in selected):
                    errors.append("TURNING_POINT_REQUIRED_BUT_ABSENT")
            elif constraint.key == "pattern_interrupt_required" and constraint.value == "true":
                if not any(n.type.value == "PATTERN_INTERRUPT" for n in selected):
                    errors.append("PATTERN_INTERRUPT_REQUIRED_BUT_ABSENT")
            elif constraint.key == "hook_and_payoff_required" and constraint.value == "true":
                types = {n.type.value for n in selected}
                if "HOOK" not in types or "PAYOFF" not in types:
                    errors.append("HOOK_AND_PAYOFF_REQUIRED_BUT_ABSENT")

        checked.append("optional_exclusions")
        if excluded:
            warnings.append(f"OPTIONAL_NODES_EXCLUDED:{len(excluded)}")

        checked.append("transition_integrity")
        known = {n.id for n in grammar.nodes}
        errors.extend(
            f"DANGLING_TRANSITION:{t.from_node}->{t.to_node}"
            for t in grammar.transitions
            if t.from_node not in known or t.to_node not in known
        )

        return NarrativeValidationResult(
            valid=not errors, checked=tuple(checked), errors=tuple(errors), warnings=tuple(warnings)
        )


def _split_qualified(grammar_id: str) -> tuple[str, str | None]:
    """Split ``id@version`` into parts. A bare id means latest."""
    if "@v" in grammar_id:
        base, _, version = grammar_id.partition("@v")
        return base, version or None
    return grammar_id, None


def _merge_constraints(*groups: tuple[ProductConstraint, ...]) -> tuple[ProductConstraint, ...]:
    """Concatenate constraint groups, de-duplicating by (key, value).

    Order is preserved and first occurrence wins, so the result is deterministic.
    A profile constraint and a grammar constraint may legitimately state the
    same rule; the intent should carry it once.
    """
    merged: list[ProductConstraint] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for constraint in group:
            key = (constraint.key, constraint.value)
            if key in seen:
                continue
            seen.add(key)
            merged.append(constraint)
    return tuple(merged)


__all__ = [
    "NarrativeCompilationError",
    "NarrativeCompiler",
    "NarrativeIntent",
    "NarrativeValidationResult",
]
