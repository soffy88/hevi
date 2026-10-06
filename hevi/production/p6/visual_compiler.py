"""HEVI P6.4 — Visual compiler and the P5.3 binding.

Produces a ``VisualIntent`` from the two upstream P6 intents plus a
``VisualGrammar``, then binds that intent to P5.3's cinematic engine.

The binding
-----------
There is exactly one way into P5.3 from P6, and it is P5.3's own:

    VisualIntent
        ↓  (declarative strategies → a VisualBeat the library understands)
    retrieve_with_evidence()      ← P5.3's single production retrieval path
        ↓
    (candidates, RecipeSelectionEvidence)

P6.4 never names a recipe. It never ranks candidates. It never builds a
``RecipeLibrary``. If P6.4 chose recipes itself it would be a second selector
sitting next to P5.3's, and the two would drift — which is precisely the
"recreate recipe_selector / shot_selector / motion_selector" failure the spec
forbids. ``test_binding_calls_p5_3_retrieve_with_evidence`` and
``test_mutation_bypassing_retrieve_with_evidence_must_fail`` pin it.

Where the chain stops, and why
-----------------------------
The system chain is

    VisualIntent → RecipeSelectionEvidence → ShotPlan → Editable Timeline

but ``ShotPlan`` and ``MotionPlan`` are owned by P0/P1
(``hevi.production.p0_pipeline``), and P5.3's own module docstring says it does
*not* "override ShotPlan, override MotionPlan". So P6.4's binding deliberately
ends at the evidence. P6.4 declares *what kind of shot is wanted*; the existing
shot and timeline systems turn that into shots. Constructing a ``ShotPlan``
here would be a second shot system, and the spec's ``NO_SECOND_SHOT`` /
``NO_SECOND_MOTION`` gates forbid exactly that. P6.4 imports no shot or motion
plan type at all, which ``test_module_defines_no_shot_or_motion_type`` asserts.

Strategy derivation is data
---------------------------
``camera_language`` → ``shot_strategy`` and ``motion_language`` →
``motion_strategy`` are fixed tables, not conditionals. Then strategy → P1's
``shot_role`` / ``motion_purpose`` so that P5.3's ``library.search`` can find real
recipes. The last hop is a vocabulary bridge; P5.3 still decides the recipe.

Determinism
-----------
``RecipeSelectionEvidence`` carries a ``timestamp``, so it is excluded from every
content hash here. Everything else is hashable and stable: 100 repeated bindings
over the same library produce one evidence fingerprint.

Not an authority
----------------
No renderer, no provider, no GPU, no CapCut, no timeline, no shot system. P5.3 is
not modified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hevi.production.p1_types import VisualBeat
from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.retrieval import retrieve_with_evidence
from hevi.production.p5_3.schema import RecipeCandidate, RecipeSelectionEvidence
from hevi.production.p6.compatibility_policy import (
    GRAMMAR_COMPATIBILITY_POLICY,
    GrammarCompatibilityPolicy,
    descriptor_for_grammar,
    descriptor_for_style,
)
from hevi.production.p6.narrative.compiler import (
    NarrativeIntent,
)
from hevi.production.p6.presenter_compiler import (
    PresenterIntent,
)
from hevi.production.p6.schema import ProductConstraint
from hevi.production.p6.visual_grammar import (
    VISUAL_GRAMMAR_COMPATIBILITY,
    VISUAL_GRAMMAR_REGISTRY,
    CameraLanguage,
    MotionLanguage,
    VisualGrammar,
    VisualGrammarCompatibility,
    VisualGrammarRegistry,
)
from hevi.production.p6.visual_style.compiler import VisualStyleIntent
from hevi.production.p6.visual_style.registry import COMPOSITION_COMPATIBILITY
from hevi.production.semantic_contract import (
    SEMANTIC_CONTRACT,
    SemanticDirective,
)

# ── declarative strategy derivation ─────────────────────────────────────
# Tables, not conditionals. camera_language is a directive; shot_strategy is its
# concrete spelling; beat_role is the P1 vocabulary P5.3 searches on.

_SHOT_STRATEGY_BY_CAMERA: dict[CameraLanguage, str] = {
    CameraLanguage.OBSERVED: "OBSERVED_COVERAGE",
    CameraLanguage.STABLE: "INSTRUCTIONAL_HOLD",
    CameraLanguage.DIRECTED: "COMPOSED_REVEAL",
    CameraLanguage.ENERGETIC: "ENERGETIC_PUSH",
    CameraLanguage.INTIMATE: "INTIMATE_DETAIL",
    CameraLanguage.DISCOVERING: "SPATIAL_DISCOVERY",
}

_MOTION_STRATEGY_BY_MOTION: dict[MotionLanguage, str] = {
    MotionLanguage.STILL: "HOLD_FRAME",
    MotionLanguage.RESTRAINED: "RESTRAINED_PUSH",
    MotionLanguage.DELIBERATE: "DELIBERATE_MOVE",
    MotionLanguage.FLUID: "FLUID_FOLLOW",
    MotionLanguage.ENERGETIC: "ENERGETIC_SURGE",
}

_BEAT_ROLE_BY_SHOT_STRATEGY: dict[str, str] = {
    "OBSERVED_COVERAGE": "FOLLOW",
    "INSTRUCTIONAL_HOLD": "EXPLAIN",
    "COMPOSED_REVEAL": "REVEAL",
    "ENERGETIC_PUSH": "PAYOFF",
    "INTIMATE_DETAIL": "DETAIL",
    "SPATIAL_DISCOVERY": "ESTABLISH",
}

#: P6.5.1 — the semantic role a motion strategy serves.
#:
#: Superseded by :data:`hevi.production.semantic_contract.SEMANTIC_CONTRACT`.
#: This table existed because a bridge has to speak P5.3's ``semantic_roles``
#: vocabulary or the 0.20 term is lost. But it was a *strategy-only* mapping, and
#: it collapsed: ``RESTRAINED_PUSH`` and ``DELIBERATE_MOVE`` both became
#: ``REVEAL``, discarding the difference between a restrained push and a
#: deliberate move. The contract keys on the whole (narrative, presenter, visual)
#: shape and carries a *set* of roles per row, so the set-to-single-string
#: collapse P5.3's scalar API forces is now a recorded, inspectable choice made in
#: :meth:`SemanticDirective.motion_purpose`.
_SEMANTIC_ROLE_BY_MOTION_STRATEGY: dict[str, str] = {
    "HOLD_FRAME": "DETAIL",
    "RESTRAINED_PUSH": "REVEAL",
    "DELIBERATE_MOVE": "REVEAL",
    "FLUID_FOLLOW": "FOLLOW",
    "ENERGETIC_SURGE": "TRANSITION",
}

#: Languages P6.3 and P6.4 both declare. A disagreement between the two layers
#: on any of these is a real conflict, not a difference of opinion.
SHARED_LANGUAGE_CHANNELS = (
    "motion_language",
    "composition_language",
    "lighting_language",
)


def _style_as_grammar(style: VisualStyleIntent) -> Any:
    """Project a compiled P6.3 style intent onto the P6.3 channel vocabulary.

    ``VisualStyleIntent`` is the *compiled* form and names its languages
    ``motion``/``composition``/``lighting``; ``VisualStyleGrammar`` is the
    declared form and names them ``*_language``. The policy speaks one shape, so
    the compiled form is lifted into it rather than a second policy being written.
    """
    from hevi.production.p6.visual_style.model import StyleCategory, VisualStyleGrammar

    return VisualStyleGrammar(
        id=style.style_id,
        version=style.style_version,
        name=style.style_id,
        category=StyleCategory.EDITORIAL,
        mood=style.mood,
        color_language=style.palette,
        composition_language=style.composition,
        texture_language=style.texture,
        motion_language=style.motion,
        lighting_language=style.lighting,
    )


def _dedupe(constraints: tuple[ProductConstraint, ...]) -> tuple[ProductConstraint, ...]:
    unique = {(c.key, c.value, c.rationale): c for c in constraints}
    return tuple(unique[k] for k in sorted(unique))


@dataclass(frozen=True)
class VisualIntentValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors)}


@dataclass(frozen=True)
class VisualIntent:
    """Compiled visual directive intent.

    Five strategies, no shots. Holds no ``ShotPlan``, no ``MotionPlan``, no
    timeline, no renderer and no provider: it states what kind of shot P5.3
    should find, and P5.3 finds it.
    """

    visual_grammar_id: str
    visual_grammar_version: str
    product_profile_id: str
    narrative_grammar_id: str = ""
    presenter_grammar_id: str = ""
    camera_style: str = ""
    shot_strategy: str = ""
    motion_strategy: str = ""
    composition_strategy: str = ""
    editing_strategy: str = ""
    lighting_strategy: str = ""
    languages: tuple[tuple[str, str], ...] = ()
    #: Channels on which P6.3 and P6.4 disagreed but were allowed to proceed.
    #: Not errors: the pairing is coherent, just less specific than it could be.
    flexible_channels: tuple[str, ...] = ()
    constraints: tuple[ProductConstraint, ...] = ()
    validation_result: VisualIntentValidationResult = field(
        default_factory=lambda: VisualIntentValidationResult(valid=False)
    )

    @property
    def qualified_id(self) -> str:
        return f"{self.visual_grammar_id}@v{self.visual_grammar_version}"

    def language_map(self) -> dict[str, str]:
        return dict(self.languages)

    def beat_role(self) -> str:
        """The P1 ``shot_role`` this intent asks P5.3 to search on."""
        try:
            return self.semantic_directive().beat_role
        except KeyError:
            return _BEAT_ROLE_BY_SHOT_STRATEGY[self.shot_strategy]

    def semantic_directive(self) -> SemanticDirective:
        """The P6.5.1 contract row for this intent's (narrative, presenter, visual) shape."""
        return SEMANTIC_CONTRACT.resolve_directive(
            self.narrative_grammar_id, self.presenter_grammar_id, self.visual_grammar_id
        )

    def motion_purpose(self) -> str:
        """The single P5.3 ``semantic_role`` this beat is scored against.

        P6.5.1: resolved from the contract, which keys on the whole grammar shape
        and carries a set of candidate roles. Falls back to the legacy
        strategy-only table only when the contract has no row for this shape, so
        an unregistered shape still produces a beat rather than raising here.
        """
        try:
            return self.semantic_directive().motion_purpose()
        except KeyError:
            return _SEMANTIC_ROLE_BY_MOTION_STRATEGY[self.motion_strategy]

    def semantic_role(self) -> str:
        """The P5.3 ``semantic_role`` this beat declares, or a graceful fallback.

        P6.5.3 puts this in ``beat.intent_id`` so P5.3's 0.30 term is reachable.
        Degrades like the other three accessors when the contract has no row for
        this shape — an unregistered combination used to compile via the legacy
        strategy table, and must keep doing so rather than raising.
        """
        try:
            return self.semantic_directive().semantic_role
        except KeyError:
            return _SEMANTIC_ROLE_BY_MOTION_STRATEGY[self.motion_strategy]

    def narrative_phase(self) -> str:
        """The narrative phase P5.3 scores against, chosen deliberately.

        Previously this was P1's ``DEVELOPMENT`` default arriving by accident.
        """
        try:
            return self.semantic_directive().narrative_phase
        except KeyError:
            return "DEVELOPMENT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_grammar_id": self.visual_grammar_id,
            "visual_grammar_version": self.visual_grammar_version,
            "product_profile_id": self.product_profile_id,
            "narrative_grammar_id": self.narrative_grammar_id,
            "presenter_grammar_id": self.presenter_grammar_id,
            "camera_style": self.camera_style,
            "shot_strategy": self.shot_strategy,
            "motion_strategy": self.motion_strategy,
            "composition_strategy": self.composition_strategy,
            "editing_strategy": self.editing_strategy,
            "lighting_strategy": self.lighting_strategy,
            "languages": [list(pair) for pair in self.languages],
            "flexible_channels": list(self.flexible_channels),
            "constraints": [c.to_dict() for c in self.constraints],
            "validation_result": self.validation_result.to_dict(),
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VisualBinding:
    """A visual intent bound to P5.3's retrieval, with the evidence it produced.

    Stops at the evidence. ``ShotPlan`` is P0/P1's to build.
    """

    intent: VisualIntent
    beat: VisualBeat
    candidates: tuple[RecipeCandidate, ...]
    evidence: RecipeSelectionEvidence

    @property
    def selected_recipe_id(self) -> str:
        return self.evidence.selected_recipe_id

    @property
    def selected_version(self) -> str:
        return self.evidence.selected_version

    def rejected_recipe_ids(self) -> tuple[str, ...]:
        return tuple(self.evidence.rejected_candidates)

    def evidence_fingerprint(self) -> str:
        """Stable fingerprint of the decision.

        ``timestamp`` is excluded: P5.3 documents that identical inputs give
        identical evidence *except for the timestamp*, so hashing it would make
        every binding look non-deterministic when the decision was not.
        """
        return semantic_fingerprint_of(self.evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_grammar_id": self.intent.visual_grammar_id,
            "beat_id": self.beat.beat_id,
            "shot_role": self.beat.shot_role,
            "motion_purpose": self.beat.motion_purpose,
            "selected_recipe_id": self.evidence.selected_recipe_id,
            "selected_version": self.evidence.selected_version,
            "candidate_recipe_ids": list(self.evidence.candidate_recipe_ids),
            "rejected_candidates": list(self.evidence.rejected_candidates),
            "evidence_fingerprint": self.evidence_fingerprint(),
        }


class VisualCompiler:
    """Compiles visual grammars into intent and binds intent to P5.3."""

    compiler_id = "p6_4_visual_binding"

    def __init__(
        self,
        registry: VisualGrammarRegistry | None = None,
        compatibility: VisualGrammarCompatibility | None = None,
        compatibility_policy: GrammarCompatibilityPolicy | None = None,
    ) -> None:
        self._compatibility_policy_obj = compatibility_policy
        self._registry = registry if registry is not None else VISUAL_GRAMMAR_REGISTRY
        self._compatibility = (
            compatibility if compatibility is not None else VISUAL_GRAMMAR_COMPATIBILITY
        )

    # ── resolution ────────────────────────────────────────────────────────

    def _compatibility_policy(self) -> GrammarCompatibilityPolicy:
        """The compatibility policy. Injectable for tests; production is global."""
        return self._compatibility_policy_obj or GRAMMAR_COMPATIBILITY_POLICY

    def _flexible_channels(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        grammar: VisualGrammar,
        style: VisualStyleIntent | None,
    ) -> tuple[str, ...]:
        """Which channels this pairing is allowed to be loose about."""
        if style is None:
            return ()
        return self._compatibility_policy().evaluate(
            descriptor_for_style(_style_as_grammar(style)),
            descriptor_for_grammar(grammar),
        ).flexible_channels

    def resolve_grammar(
        self, ref: str, version: str | None = None
    ) -> VisualGrammar:
        """Resolve a grammar reference or raise. Never falls back to a default."""
        if not ref or not ref.strip():
            raise KeyError("VISUAL_GRAMMAR_NOT_FOUND:profile declares no visual_grammar_id")
        grammar = self._registry.get(ref.strip(), version)
        if grammar is None:
            raise KeyError(f"UNKNOWN_VISUAL_GRAMMAR:{ref}")
        return grammar

    # ── compatibility ─────────────────────────────────────────────────────

    def check_compatibility(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        grammar: VisualGrammar,
        style: VisualStyleIntent | None = None,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []

        permitted = self._compatibility.allowed(narrative.grammar_id)
        if permitted is not None and grammar.visual_grammar_id not in permitted:
            errors.append(
                f"INCOMPATIBLE_VISUAL_PAIRING:narrative={narrative.grammar_id}"
                f":grammar={grammar.visual_grammar_id}"
                f":permitted={'|'.join(sorted(permitted))}"
            )

        # Presenter → composition. Reuses P6.3's table rather than restating it,
        # so the performed-shape rule has exactly one authority.
        allowed_compositions = COMPOSITION_COMPATIBILITY.get(presenter.grammar_id)
        if (
            allowed_compositions is not None
            and grammar.composition_language not in allowed_compositions
        ):
            errors.append(
                f"INCOMPATIBLE_VISUAL_PAIRING:presenter={presenter.grammar_id}"
                f":composition={grammar.composition_language.value}"
            )

        # P6.3 / P6.4 coherence, decided by the P6.5.2 constraint model.
        #
        # This used to require equality across all three shared channels, which is
        # what produced G-14's diagonal: 3 of 24 pairings usable, and
        # `commercial_clean`, `archival_history`, `future_tech` and
        # `corporate_clean` all dead. Agreement is now decided by
        # `GRAMMAR_COMPATIBILITY_POLICY`, which gates motion (the one channel
        # where disagreement is a contradiction rather than extra work) and treats
        # lighting and composition as flexible.
        if style is not None:
            decision = self._compatibility_policy().evaluate(
                descriptor_for_style(_style_as_grammar(style)),
                descriptor_for_grammar(grammar),
            )
            # Only *blocking* rules are errors. An advisory means the pairing is
            # usable with less room, which is recorded on the intent
            # (`flexible_channels`) rather than raised — an earlier version of this
            # appended advisories to `errors` too, which made "flexible" refuse the
            # pair and silently defeated the whole point of the constraint model.
            errors.extend(
                f"VISUAL_GRAMMAR_STYLE_CONFLICT:{reason}"
                for reason in decision.blocking
            )

        return (not errors), errors

    # ── compile ───────────────────────────────────────────────────────────

    def compile(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        grammar: VisualGrammar,
        style: VisualStyleIntent | None = None,
    ) -> VisualIntent:
        ok, errors = self.validate(narrative, presenter, grammar, style)
        if not ok:
            raise ValueError(";".join(errors))

        return VisualIntent(
            visual_grammar_id=grammar.visual_grammar_id,
            visual_grammar_version=grammar.version,
            product_profile_id=narrative.product_profile_id,
            narrative_grammar_id=narrative.grammar_id,
            presenter_grammar_id=presenter.grammar_id,
            camera_style=grammar.camera_language.value,
            shot_strategy=_SHOT_STRATEGY_BY_CAMERA[grammar.camera_language],
            motion_strategy=_MOTION_STRATEGY_BY_MOTION[grammar.motion_language],
            composition_strategy=grammar.composition_language.value,
            editing_strategy=grammar.editing_language.value,
            lighting_strategy=grammar.lighting_language.value,
            languages=tuple(sorted(grammar.languages().items())),
            flexible_channels=self._flexible_channels(narrative, presenter, grammar, style),
            constraints=_dedupe(grammar.constraints),
            validation_result=VisualIntentValidationResult(valid=True),
        )

    def validate(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        grammar: VisualGrammar,
        style: VisualStyleIntent | None = None,
    ) -> tuple[bool, list[str]]:
        ok, grammar_errors = self._registry.validate(
            grammar.visual_grammar_id, grammar.version
        )
        if not ok:
            return False, list(grammar_errors)

        errors: list[str] = []
        if not narrative.validation_result.valid:
            errors.append("NARRATIVE_INTENT_INVALID")
        if not presenter.validation_result.valid:
            errors.append("PRESENTER_INTENT_INVALID")
        if not narrative.grammar_id:
            errors.append("NARRATIVE_GRAMMAR_ID_MISSING")
        if not presenter.grammar_id:
            errors.append("PRESENTER_GRAMMAR_ID_MISSING")
        for channel, value in sorted(grammar.languages().items()):
            if not value:
                errors.append(f"EMPTY_VISUAL_LANGUAGE:{channel}")

        ok_pair, pair_errors = self.check_compatibility(
            narrative, presenter, grammar, style
        )
        if not ok_pair:
            errors.extend(pair_errors)
        return (not errors), errors

    # ── P5.3 binding ──────────────────────────────────────────────────────

    def visual_beat_for(
        self,
        intent: VisualIntent,
        *,
        beat_id: str,
        narration_span: str = "",
        start_s: float = 0.0,
        end_s: float = 4.0,
        motion_purpose: str = "",
    ) -> VisualBeat:
        """Build the P1 ``VisualBeat`` that expresses this intent to P5.3.

        This is a *vocabulary bridge*: it hands P5.3's library a beat it can
        search on. It selects nothing — the recipe is P5.3's decision, made in
        ``retrieve_with_evidence``. It also creates no shot: ``VisualBeat`` is the
        pre-existing P1 request type, and P0/P1 build the ``ShotPlan``.
        """
        return VisualBeat(
            beat_id=beat_id,
            timeline_start_s=start_s,
            timeline_end_s=end_s,
            narration_span=narration_span,
            # The contract's ``semantic_id`` — a P5.3 ``semantic_role``. This is
            # what makes P5.3's 0.30 intent term reachable (P6.5.3). It used to
            # carry P6's own qualified grammar id, which could never equal a
            # recipe label, so the term was structurally dead.
            #
            # It names a *layer's* job, not a recipe: P6 still selects nothing and
            # recommends nothing. `semantic_roles` is the vocabulary P5.3 already
            # used to score `motion_purpose`, so this reuses an existing surface
            # rather than adding one.
            intent_id=intent.semantic_role(),
            shot_role=intent.beat_role(),
            motion_purpose=motion_purpose or intent.motion_purpose(),
            narrative_phase=intent.narrative_phase(),
            required_visual=(
                f"{intent.camera_style}/{intent.composition_strategy}"
                f"/{intent.lighting_strategy}"
            ),
        )

    def bind(
        self,
        library: RecipeLibrary,
        intent: VisualIntent,
        *,
        beat: VisualBeat | None = None,
        beat_id: str = "",
        profile_id: str = "",
        duration: float | None = None,
        renderer_capabilities: list[str] | None = None,
        available_assets: list[str] | None = None,
    ) -> VisualBinding:
        """Bind a visual intent to P5.3 through its single retrieval path.

        There is no alternative route and no local fallback. If P5.3 returns no
        candidates the binding fails closed rather than inventing a recipe,
        because a visual directive with nothing filmable behind it is a defect
        to surface, not to paper over.
        """
        resolved_beat = beat or self.visual_beat_for(
            intent, beat_id=beat_id or f"{intent.qualified_id}#beat0"
        )

        candidates, evidence = retrieve_with_evidence(
            library,
            resolved_beat,
            profile_id=profile_id,
            available_assets=available_assets,
            renderer_capabilities=renderer_capabilities,
            duration=duration,
        )
        if not candidates or not evidence.selected_recipe_id:
            raise LookupError(
                f"VISUAL_BINDING_NO_RECIPE:{intent.qualified_id}:"
                f"beat={resolved_beat.beat_id}:role={resolved_beat.shot_role}"
            )
        return VisualBinding(
            intent=intent,
            beat=resolved_beat,
            candidates=tuple(candidates),
            evidence=evidence,
        )


def semantic_fingerprint_of(evidence: RecipeSelectionEvidence) -> str:
    """Stable fingerprint of a P5.3 selection decision.

    ``timestamp`` is excluded: P5.3 documents identical evidence *except* for it,
    so hashing it would make every decision look nondeterministic when the
    decision was not. Shared with :meth:`VisualBinding.evidence_fingerprint`.
    """
    payload = {
        "visual_beat_id": evidence.visual_beat_id,
        "selected_recipe_id": evidence.selected_recipe_id,
        "selected_version": evidence.selected_version,
        "candidate_recipe_ids": list(evidence.candidate_recipe_ids),
        "rejected_candidates": list(evidence.rejected_candidates),
        "selection_factors": dict(sorted(evidence.selection_factors.items())),
        "rejection_reasons": dict(sorted(evidence.rejection_reasons.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "SHARED_LANGUAGE_CHANNELS",
    "VisualBinding",
    "VisualCompiler",
    "VisualIntent",
    "VisualIntentValidationResult",
    "semantic_fingerprint_of",
]
