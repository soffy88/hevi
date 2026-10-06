"""HEVI P6.2 — Presenter compiler.

Compiles a P6.1 ``NarrativeIntent`` plus a profile's presenter grammar into a
``PresenterIntent``.

    ProductProfile.presenter_grammar_id
        -> PRESENTER_GRAMMAR_REGISTRY.resolve()
    NarrativeIntent
        -> PresenterCompiler.compile()
        -> PresenterIntent

The narrative is an *input*, not something recomputed: the presenter performs
the narrative that already exists. That ordering is what makes the two grammars
composable instead of competing.

Four properties, each verified by an executing test:

``deterministic``
    Identical inputs produce a byte-identical ``content_hash()``. Node order comes
    from the grammar's declared ``order``, which P6.2 requires to be unique.

``fail_closed``
    Missing grammar id raises ``PRESENTER_GRAMMAR_NOT_FOUND``; an unregistered id
    raises ``UNKNOWN_PRESENTER_GRAMMAR``; an incompatible narrative/presenter
    pairing raises ``INCOMPATIBLE_GRAMMAR_PAIRING``; a grammar whose required
    nodes are absent raises rather than returning an empty list. There is no
    fallback presenter and no default — a video that silently got the wrong
    presenter would be worse than one that refused to compile.

``serializable``
    ``to_dict()`` round-trips through JSON and the hash derives from it.

``provider_independent``
    Requirements are declared as ``ProductConstraint`` records. No provider, model
    or renderer is named anywhere in this module.

Not an authority
----------------
Emits presentation *intent*. It does not select a provider, cast a voice, drive a
camera, or generate a frame. ``hevi.providers``, ``hevi.renderers`` and the P5.1
presenter/voice authorities are untouched and unimported.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hevi.production.p6.narrative.compiler import NarrativeIntent
from hevi.production.p6.presenter import (
    PresenterGrammar,
    PresenterNode,
    PresenterNodeType,
    PresenterRequirements,
)
from hevi.production.p6.presenter_registry import (
    GRAMMAR_COMPATIBILITY_REGISTRY,
    PRESENTER_GRAMMAR_REGISTRY,
    GrammarCompatibilityRegistry,
    PresenterGrammarRegistry,
)
from hevi.production.p6.schema import ProductConstraint, ProductProfile


class PresenterCompilationError(ValueError):
    """Raised when a presenter intent cannot be produced.

    A ``ValueError`` because the cause is a defect in the profile or grammar, not
    a runtime fault.
    """


@dataclass(frozen=True)
class PresenterValidationResult:
    """What compilation checked, and what it concluded.

    Recorded on the intent so a later stage can see validation ran rather than
    inferring it from the presence of an intent.
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
class PresenterIntent:
    """Compiled presenter intent for one product.

    Holds an ordered node sequence and channel-separated requirements. It holds
    no provider, no voice artifact, no camera move and no renderer: those belong
    to the existing authorities and are resolved downstream from what is declared
    here.
    """

    grammar_id: str
    grammar_version: str
    product_profile_id: str
    narrative_grammar_id: str = ""
    ordered_nodes: tuple[PresenterNode, ...] = ()
    presentation_style: str = ""
    speaker_requirements: tuple[ProductConstraint, ...] = ()
    visual_requirements: tuple[ProductConstraint, ...] = ()
    audio_requirements: tuple[ProductConstraint, ...] = ()
    constraints: tuple[ProductConstraint, ...] = ()
    validation_result: PresenterValidationResult = field(
        default_factory=lambda: PresenterValidationResult(valid=False)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "grammar_id": self.grammar_id,
            "grammar_version": self.grammar_version,
            "product_profile_id": self.product_profile_id,
            "narrative_grammar_id": self.narrative_grammar_id,
            "ordered_nodes": [n.to_dict() for n in self.ordered_nodes],
            "presentation_style": self.presentation_style,
            "speaker_requirements": [c.to_dict() for c in self.speaker_requirements],
            "visual_requirements": [c.to_dict() for c in self.visual_requirements],
            "audio_requirements": [c.to_dict() for c in self.audio_requirements],
            "constraints": [c.to_dict() for c in self.constraints],
            "validation_result": self.validation_result.to_dict(),
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def sequence(self) -> tuple[str, ...]:
        return tuple(n.type.value for n in self.ordered_nodes)

    def node_ids(self) -> tuple[str, ...]:
        return tuple(n.id for n in self.ordered_nodes)


class PresenterCompiler:
    """Compiles a narrative intent plus a profile's presenter grammar into intent.

    Stateless and reusable. Holds no per-compile state, so the same instance
    compiles any number of profiles identically.
    """

    compiler_id = "p6_2_presenter"

    def __init__(
        self,
        registry: PresenterGrammarRegistry | None = None,
        compatibility: GrammarCompatibilityRegistry | None = None,
    ) -> None:
        # Default to the single module-level authorities. Injecting one is for
        # tests needing isolation; production uses the one registry.
        self._registry = registry if registry is not None else PRESENTER_GRAMMAR_REGISTRY
        self._compatibility = (
            compatibility if compatibility is not None else GRAMMAR_COMPATIBILITY_REGISTRY
        )

    @property
    def registry(self) -> PresenterGrammarRegistry:
        return self._registry

    @property
    def compatibility(self) -> GrammarCompatibilityRegistry:
        return self._compatibility

    # ── Resolution ──────────────────────────────────────────────────────

    def resolve_presenter_grammar(self, profile: ProductProfile) -> PresenterGrammar:
        """Resolve the profile's presenter grammar, or fail closed.

        Two distinct failures, deliberately distinguished so the error names the
        actual defect: a profile that never declared one, versus one that
        declared something unregistered.
        """
        if not isinstance(profile, ProductProfile):
            raise PresenterCompilationError(
                f"NOT_A_PRODUCT_PROFILE:{type(profile).__name__}"
            )
        grammar_ref = profile.presenter_grammar_id
        if not grammar_ref:
            raise PresenterCompilationError(
                f"PRESENTER_GRAMMAR_NOT_FOUND:{profile.id} declares no presenter grammar"
            )
        try:
            return self._registry.resolve(grammar_ref)
        except KeyError as exc:
            raise PresenterCompilationError(
                f"UNKNOWN_PRESENTER_GRAMMAR:{grammar_ref}"
            ) from exc

    def check_compatibility(
        self, narrative_grammar_id: str, presenter_grammar_id: str
    ) -> None:
        """Refuse an incoherent narrative/presenter pairing.

        The rule is a table lookup, not a conditional. A narrative absent from
        the table permits any registered presenter.
        """
        if not self._compatibility.is_compatible(narrative_grammar_id, presenter_grammar_id):
            permitted = sorted(self._compatibility.allowed(narrative_grammar_id) or ())
            raise PresenterCompilationError(
                f"INCOMPATIBLE_GRAMMAR_PAIRING:narrative={narrative_grammar_id} "
                f"presenter={presenter_grammar_id} permitted={','.join(permitted)}"
            )

    # ── Compilation ─────────────────────────────────────────────────────

    def compile(
        self,
        profile: ProductProfile,
        narrative_intent: NarrativeIntent,
    ) -> PresenterIntent:
        """Compile one profile's presenter grammar against its narrative."""
        return self.compile_with(
            profile,
            narrative_intent,
            include_optional=True,
            extra_constraints=(),
        )

    def compile_with(
        self,
        profile: ProductProfile,
        narrative_intent: NarrativeIntent,
        *,
        include_optional: bool = True,
        extra_constraints: tuple[ProductConstraint, ...] = (),
    ) -> PresenterIntent:
        """Compile with explicit control over optional nodes and constraints."""
        if not isinstance(narrative_intent, NarrativeIntent):
            raise PresenterCompilationError(
                f"NOT_A_NARRATIVE_INTENT:{type(narrative_intent).__name__}"
            )
        if not narrative_intent.validation_result.valid:
            raise PresenterCompilationError(
                "NARRATIVE_INTENT_INVALID:"
                f"{';'.join(narrative_intent.validation_result.errors)}"
            )

        grammar = self.resolve_presenter_grammar(profile)
        self.check_compatibility(
            narrative_intent.grammar_id, grammar.id
        )

        ordered = grammar.ordered_nodes()
        selected: list[PresenterNode] = []
        for node in ordered:
            if not node.required and not include_optional:
                continue
            selected.append(node)

        effective_constraints = _merge_constraints(
            profile.constraints, grammar.constraints, extra_constraints
        )
        effective_requirements = _merge_requirements(
            grammar.requirements, narrative_intent.constraints
        )

        validation = self._validate(
            grammar, narrative_intent, selected, effective_constraints
        )
        if not validation.valid:
            raise PresenterCompilationError(
                f"PRESENTER_VALIDATION_FAILED:{profile.id}:{';'.join(validation.errors)}"
            )

        return PresenterIntent(
            grammar_id=grammar.id,
            grammar_version=grammar.version,
            product_profile_id=profile.id,
            narrative_grammar_id=narrative_intent.grammar_id,
            ordered_nodes=tuple(selected),
            presentation_style=effective_requirements.presentation_style
            or grammar.requirements.presentation_style,
            speaker_requirements=effective_requirements.speaker_requirements,
            visual_requirements=effective_requirements.visual_requirements,
            audio_requirements=effective_requirements.audio_requirements,
            constraints=effective_constraints,
            validation_result=validation,
        )

    # ── Validation ──────────────────────────────────────────────────────

    def _validate(
        self,
        grammar: PresenterGrammar,
        narrative_intent: NarrativeIntent,
        selected: list[PresenterNode],
        effective_constraints: tuple[ProductConstraint, ...],
    ) -> PresenterValidationResult:
        checked: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []

        checked.append("non_empty_sequence")
        if not selected:
            # Never return an empty presenter. An empty list would compile into a
            # video with nobody presenting it.
            errors.append("EMPTY_PRESENTER_SEQUENCE")
            return PresenterValidationResult(
                False, tuple(checked), tuple(errors), tuple(warnings)
            )

        checked.append("required_nodes_present")
        selected_ids = {n.id for n in selected}
        missing = [nid for nid in grammar.required_node_ids() if nid not in selected_ids]
        if missing:
            errors.append(f"REQUIRED_PRESENTER_NODES_EXCLUDED:{','.join(sorted(missing))}")

        checked.append("grammar_constraints")
        types = {n.type.value for n in selected}
        for constraint in effective_constraints:
            key, value = constraint.key, constraint.value
            if key == "min_nodes" and value.isdigit() and len(selected) < int(value):
                errors.append(f"MIN_PRESENTER_NODES_VIOLATED:{len(selected)}<{value}")
            elif key == "identity_required" and value == "true":
                if PresenterNodeType.IDENTITY.value not in types:
                    errors.append("PRESENTER_IDENTITY_REQUIRED_BUT_ABSENT")
            elif key == "authority_required" and value == "true":
                if PresenterNodeType.AUTHORITY.value not in types:
                    errors.append("PRESENTER_AUTHORITY_REQUIRED_BUT_ABSENT")
            elif key == "evidence_required" and value == "true":
                if PresenterNodeType.EVIDENCE.value not in types:
                    errors.append("PRESENTER_EVIDENCE_REQUIRED_BUT_ABSENT")
            elif key == "evidence_before_interpretation" and value == "true":
                order = {n.type.value: i for i, n in enumerate(selected)}
                if (
                    PresenterNodeType.EVIDENCE.value in order
                    and PresenterNodeType.INTERPRETATION.value in order
                    and order[PresenterNodeType.EVIDENCE.value]
                    > order[PresenterNodeType.INTERPRETATION.value]
                ):
                    errors.append("PRESENTER_EVIDENCE_AFTER_INTERPRETATION")
            elif (
                key == "reconstruction_disclosure_required"
                and value == "true"
                and PresenterNodeType.INTERPRETATION.value not in types
            ):
                errors.append("RECONSTRUCTION_DISCLOSURE_REQUIRED_BUT_ABSENT")

        checked.append("narrative_alignment")
        # A presenter that never appears in the narrative's own vocabulary is
        # worth a warning, not an error: the two vocabularies overlap only where
        # the function coincides, and a presenter may legitimately add a beat the
        # narrative does not name.
        narrative_types = set(narrative_intent.sequence)
        shared = types & narrative_types
        if not shared:
            warnings.append("NO_NARRATIVE_PRESENTER_NODE_OVERLAP")

        checked.append("requirements_present")
        if grammar.requirements.is_empty:
            warnings.append("PRESENTER_GRAMMAR_WITHOUT_REQUIREMENTS")

        return PresenterValidationResult(
            valid=not errors,
            checked=tuple(checked),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )


def _merge_constraints(
    *groups: tuple[ProductConstraint, ...],
) -> tuple[ProductConstraint, ...]:
    """Concatenate constraint groups, de-duplicating by (key, value).

    Order preserved, first occurrence wins, so the result is deterministic.
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


def _merge_requirements(
    primary: PresenterRequirements, secondary_constraints: tuple[ProductConstraint, ...]
) -> PresenterRequirements:
    """Fold narrative constraints into the presenter's requirement channels.

    A narrative constraint that names a requirement channel is a requirement of
    that channel. Routing it through here rather than duplicating it into all
    three keeps ``speaker_requirements`` honest — a caption constraint is not a
    speaker requirement.
    """
    speaker = list(primary.speaker_requirements)
    visual = list(primary.visual_requirements)
    audio = list(primary.audio_requirements)
    for constraint in secondary_constraints:
        if constraint.key.startswith("speaker_"):
            speaker.append(constraint)
        elif constraint.key.startswith("visual_"):
            visual.append(constraint)
        elif constraint.key.startswith("audio_"):
            audio.append(constraint)
    return PresenterRequirements(
        speaker_requirements=tuple(speaker),
        visual_requirements=tuple(visual),
        audio_requirements=tuple(audio),
        presentation_style=primary.presentation_style,
    )


__all__ = [
    "PresenterCompilationError",
    "PresenterCompiler",
    "PresenterIntent",
    "PresenterValidationResult",
]
