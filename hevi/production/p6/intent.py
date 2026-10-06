"""HEVI P6.1 / P6.2 / P6.3 — Product intent: the runtime boundary surface.

``compile_product_intent()`` is the single entry point that turns a
``ProductProfile`` into a ``ProductIntent`` the existing runtime can consume.

    ProductProfile
      -> ProductProfileRegistry          (P6.0 — the profile authority)
      -> narrative_grammar_id
      -> NARRATIVE_GRAMMAR_REGISTRY      (P6.1 — the narrative authority)
      -> NarrativeCompiler               (P6.1)
      -> NarrativeIntent
      -> presenter_grammar_id
      -> PRESENTER_GRAMMAR_REGISTRY      (P6.2 — the presenter authority)
      -> PresenterCompiler               (P6.2)
      -> PresenterIntent
      -> visual_style_id
      -> VISUAL_STYLE_REGISTRY           (P6.3 - the visual style authority)
      -> VisualStyleCompiler             (P6.3)
      -> VisualStyleIntent
      -> ProductIntent                   (this module)
      -> existing production runtime     (P0-P5)

P6.1 compiles the narrative. P6.2 compiles the presenter *against* that
narrative, and cross-validates the pairing through
``GRAMMAR_COMPATIBILITY_REGISTRY`` — which is how the P6.1 gap (a profile could
declare a narrative and a presenter that had nothing to do with each other) is
closed, as data rather than as a conditional.

P6.3 compiles the visual style against *both* upstream intents. The narrative
decides which looks may serve the arc; the presenter decides which compositions
may carry the performance. A style that satisfies neither is refused rather than
repaired, because a repaired style would be a style nobody chose.

What this does not do
---------------------
It does not call a renderer, build a timeline, create a shot, resolve an asset,
select a provider, or judge quality. Those are P5.2, P1, P0, P5.2,
``hevi.providers`` and ``hevi.verdict`` respectively, and this module imports none
of them. A ``ProductIntent`` is intent: the product identity, the compiled
narrative, the compiled presenter, the compiled visual style, and the
constraints that bound production.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from hevi.production.p6.narrative.compiler import (
    NarrativeCompiler,
    NarrativeIntent,
)
from hevi.production.p6.narrative.registry import NARRATIVE_GRAMMAR_REGISTRY
from hevi.production.p6.presenter_compiler import (
    PresenterCompiler,
    PresenterIntent,
)
from hevi.production.p6.presenter_registry import (
    GRAMMAR_COMPATIBILITY_REGISTRY,
    PRESENTER_GRAMMAR_REGISTRY,
)
from hevi.production.p6.schema import ProductConstraint, ProductProfile
from hevi.production.p6.visual_compiler import VisualCompiler, VisualIntent
from hevi.production.p6.visual_grammar import (
    VISUAL_GRAMMAR_COMPATIBILITY,
    VISUAL_GRAMMAR_REGISTRY,
)
from hevi.production.p6.visual_style.compiler import (
    VisualStyleCompiler,
    VisualStyleIntent,
)
from hevi.production.p6.visual_style.registry import (
    STYLE_COMPATIBILITY_REGISTRY,
    VISUAL_STYLE_REGISTRY,
)

#: Product types that are inherently narrative. A profile of one of these kinds
#: must compile a narrative before production; a profile without one is
#: incomplete rather than exempt. This is a *requirement table*, not branching:
#: it maps a product type to whether narrative is required, and compilation
#: still resolves the grammar generically. No code path compares a product type
#: to choose a grammar.
NARRATIVE_REQUIRED_PRODUCT_TYPES: frozenset[str] = frozenset(
    {
        "P01_AVATAR_EXPLAINER",
        "P02_NARRATED_KNOWLEDGE",
        "P03_HISTORICAL_REENACTMENT",
        "P04_CHARACTER_DOCUMENTARY",
        "P05_DOCUMENTARY",
        "P06_NARRATIVE_FILM",
        "P07_CINEMATIC_KNOWLEDGE",
        "P08_COMMERCIAL",
        "P09_TUTORIAL",
        "P10_SHORT_FORM",
    }
)


class ProductIntentError(ValueError):
    """Raised when a product intent cannot be produced."""


@dataclass(frozen=True)
class ProductIntent:
    """Compiled product intent.

    Carries the product's identity, its compiled narrative, its compiled
    presenter, and the constraints that bound production. It is *not* a plan, a
    shot list, or a render job.
    """

    product_profile_id: str
    product_profile_version: str
    product_type: str
    narrative_intent: NarrativeIntent
    presenter_intent: PresenterIntent | None = None
    visual_style_intent: VisualStyleIntent | None = None
    visual_intent: VisualIntent | None = None
    constraints: tuple[ProductConstraint, ...] = ()
    profile_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_profile_id": self.product_profile_id,
            "product_profile_version": self.product_profile_version,
            "product_type": self.product_type,
            "narrative_intent": self.narrative_intent.to_dict(),
            "presenter_intent": (
                self.presenter_intent.to_dict() if self.presenter_intent else None
            ),
            "visual_style_intent": (
                self.visual_style_intent.to_dict() if self.visual_style_intent else None
            ),
            "visual_intent": (
                self.visual_intent.to_dict() if self.visual_intent else None
            ),
            "constraints": [c.to_dict() for c in self.constraints],
            "profile_refs": list(self.profile_refs),
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def narrative_sequence(self) -> tuple[str, ...]:
        return self.narrative_intent.sequence

    def presenter_sequence(self) -> tuple[str, ...]:
        """The presenter node sequence, or empty when no presenter is declared."""
        return self.presenter_intent.sequence() if self.presenter_intent else ()

    def visual_languages(self) -> dict[str, str]:
        """The six resolved visual languages, or empty when no style is declared."""
        return self.visual_style_intent.languages() if self.visual_style_intent else {}

    def visual_strategies(self) -> dict[str, str]:
        """The five P6.4 strategies, or empty when no visual grammar is declared."""
        if not self.visual_intent:
            return {}
        return {
            "camera_style": self.visual_intent.camera_style,
            "shot_strategy": self.visual_intent.shot_strategy,
            "motion_strategy": self.visual_intent.motion_strategy,
            "composition_strategy": self.visual_intent.composition_strategy,
            "editing_strategy": self.visual_intent.editing_strategy,
        }


def compile_product_intent(
    product_profile: ProductProfile,
    *,
    narrative_compiler: NarrativeCompiler | None = None,
    presenter_compiler: PresenterCompiler | None = None,
    visual_style_compiler: VisualStyleCompiler | None = None,
    visual_compiler: VisualCompiler | None = None,
    include_optional: bool = True,
    extra_constraints: tuple[ProductConstraint, ...] = (),
) -> ProductIntent:
    """Compile a product profile into a ``ProductIntent``.

    Resolution order: the profile comes from the caller's hands (the registry is
    the authority for *which* profiles exist, and callers normally resolve
    through it), then the narrative grammar is resolved from
    ``narrative_grammar_id`` through the single narrative registry, then the
    presenter grammar from ``presenter_grammar_id`` through the single presenter
    registry and checked against the narrative it will perform, then the visual
    style from ``visual_style_id`` through the single visual style registry and
    checked against both.

    Fail-closed throughout. A profile with no narrative, a narrative type that is
    not registered, a presenter that is not registered, a narrative/presenter
    pairing the compatibility table does not permit, or a grammar whose
    constraints cannot be satisfied raises rather than producing a partial intent.

    The presenter and the visual style are each optional at the profile level — a
    profile that declares no ``presenter_grammar_id`` compiles narrative only —
    but a profile that declares one gets no fallback if it cannot be resolved.

    The visual style is the exception that proves the rule: it needs *both*
    upstream intents, so declaring ``visual_style_id`` on a profile that compiled
    no presenter is a malformed declaration rather than a partial compile. That
    raises instead of quietly styling a video with nobody presenting it.
    """
    if not isinstance(product_profile, ProductProfile):
        raise ProductIntentError(f"NOT_A_PRODUCT_PROFILE:{type(product_profile).__name__}")

    # Requirement check, not behavioural branching: it asks whether a grammar id
    # was declared. It does not choose one, and the compiler below resolves
    # whatever was declared through the registry. This is why the guard in
    # tests/test_p6_1_narrative.py::test_no_product_branching permits a
    # membership test against a table but rejects selecting behaviour per type.
    product_type = product_profile.product_type.value
    missing_grammar = not product_profile.narrative_grammar_id
    if missing_grammar and product_type in NARRATIVE_REQUIRED_PRODUCT_TYPES:
        raise ProductIntentError(
            f"MISSING_NARRATIVE_GRAMMAR_ID:{product_profile.id} is a narrative "
            f"product ({product_type}) and must declare a narrative grammar"
        )

    compiler = narrative_compiler or NarrativeCompiler(NARRATIVE_GRAMMAR_REGISTRY)
    narrative_intent = compiler.compile_with(
        product_profile,
        include_optional=include_optional,
        extra_constraints=extra_constraints,
    )

    # A profile may declare a presenter or not. Declaring one is a hard
    # requirement: it is resolved with no fallback, so a typo cannot silently
    # yield a video with nobody presenting it.
    presenter_intent: PresenterIntent | None = None
    if product_profile.presenter_grammar_id:
        p_compiler = presenter_compiler or PresenterCompiler(
            PRESENTER_GRAMMAR_REGISTRY, GRAMMAR_COMPATIBILITY_REGISTRY
        )
        presenter_intent = p_compiler.compile_with(
            product_profile,
            narrative_intent,
            include_optional=include_optional,
            extra_constraints=extra_constraints,
        )

    visual_style_intent: VisualStyleIntent | None = None
    if product_profile.visual_style_id:
        if presenter_intent is None:
            # Fail closed: a style needs a performance to be styled *for*. This
            # is a declaration-consistency check, not product branching.
            raise ProductIntentError(
                f"MISSING_PRESENTER_FOR_VISUAL_STYLE:{product_profile.id} declares "
                f"visual_style_id={product_profile.visual_style_id!r} but no "
                "presenter_grammar_id, and a visual style has nothing to style "
                "without a performance"
            )
        v_compiler = visual_style_compiler or VisualStyleCompiler(
            VISUAL_STYLE_REGISTRY, STYLE_COMPATIBILITY_REGISTRY
        )
        try:
            visual_style_intent = v_compiler.compile_product_intent(
                product_profile.id,
                narrative_intent,
                presenter_intent,
                product_profile.visual_style_id,
            )
        except KeyError as exc:
            raise ProductIntentError(str(exc)) from exc
        except ValueError as exc:
            raise ProductIntentError(
                f"VISUAL_STYLE_INTENT_INVALID:{product_profile.id}:{exc}"
            ) from exc

    constraints = narrative_intent.constraints
    if presenter_intent is not None:
        # Presenter constraints are a superset when a presenter compiled: the
        # narrative's own constraints were already folded in, plus the
        # presenter's. Merging by (key, value) keeps it deterministic.
        merged: list[ProductConstraint] = list(narrative_intent.constraints)
        seen = {(c.key, c.value) for c in merged}
        for constraint in presenter_intent.constraints:
            if (constraint.key, constraint.value) not in seen:
                seen.add((constraint.key, constraint.value))
                merged.append(constraint)
        constraints = tuple(merged)

    if visual_style_intent is not None:
        # Same superset rule one stage down: the style's declared constraints join
        # the narrative's and the presenter's, deduplicated by (key, value) so the
        # merge stays order-stable.
        merged = list(constraints)
        seen = {(c.key, c.value) for c in merged}
        for constraint in visual_style_intent.constraints:
            if (constraint.key, constraint.value) not in seen:
                seen.add((constraint.key, constraint.value))
                merged.append(constraint)
        constraints = tuple(merged)

    visual_intent: VisualIntent | None = None
    if product_profile.visual_grammar_id:
        if presenter_intent is None:
            raise ProductIntentError(
                f"MISSING_PRESENTER_FOR_VISUAL_GRAMMAR:{product_profile.id} declares "
                f"visual_grammar_id={product_profile.visual_grammar_id!r} but no "
                "presenter_grammar_id"
            )
        vg_compiler = visual_compiler or VisualCompiler(
            VISUAL_GRAMMAR_REGISTRY, VISUAL_GRAMMAR_COMPATIBILITY
        )
        try:
            # The P6.3 style intent is passed in so the two visual layers are
            # cross-checked. A pair whose shared languages disagree is refused.
            visual_intent = vg_compiler.compile(
                narrative_intent,
                presenter_intent,
                vg_compiler.resolve_grammar(product_profile.visual_grammar_id),
                style=visual_style_intent,
            )
        except KeyError as exc:
            raise ProductIntentError(str(exc)) from exc
        except ValueError as exc:
            raise ProductIntentError(
                f"VISUAL_INTENT_INVALID:{product_profile.id}:{exc}"
            ) from exc

    if visual_intent is not None:
        merged = list(constraints)
        seen = {(c.key, c.value) for c in merged}
        for constraint in visual_intent.constraints:
            if (constraint.key, constraint.value) not in seen:
                seen.add((constraint.key, constraint.value))
                merged.append(constraint)
        constraints = tuple(merged)

    return ProductIntent(
        product_profile_id=product_profile.id,
        product_profile_version=product_profile.version,
        product_type=product_type,
        narrative_intent=narrative_intent,
        presenter_intent=presenter_intent,
        visual_style_intent=visual_style_intent,
        visual_intent=visual_intent,
        constraints=constraints,
        profile_refs=product_profile.profile_refs,
    )


__all__ = [
    "NARRATIVE_REQUIRED_PRODUCT_TYPES",
    "ProductIntent",
    "ProductIntentError",
    "compile_product_intent",
]
