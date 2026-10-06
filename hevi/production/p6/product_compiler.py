"""HEVI P6.5 — The one product compiler.

Turns a customer-facing brief into a complete, filmable production blueprint:

    ProductProfile
        ↓ ProductCompiler.compile()
    ProductProductionIntent
        ├── NarrativeIntent            (P6.1)
        ├── PresenterIntent            (P6.2)
        ├── VisualStyleIntent          (P6.3)
        ├── VisualIntent               (P6.4)
        ├── RecipeSelectionEvidence    (P5.3)
        └── constraints

One compiler, ten products, zero branches
-----------------------------------------
The compiler below has never heard of history, science, marketing or any other
product. It reads four grammar references off whatever profile it is handed and
asks four existing compilers to do their part. Every per-product decision was
already made — as data — in ``product_profiles.py``.

It also has no default. A profile missing any of the four references is refused
with ``INVALID_PRODUCT_PROFILE`` rather than completed with a sensible-looking
substitute, because a silently substituted grammar produces a video nobody
specified.

The three sub-compilers are not optional
----------------------------------------
``NarrativeCompiler``, ``PresenterCompiler`` and ``VisualCompiler`` are the only
way this module produces an intent. P6.5 does not reimplement any of them, does
not reach around them, and does not post-process their output into a second
shape. ``test_compiler_delegates_to_all_three_sub_compilers`` and
``test_mutation_bypassing_narrative_compiler_must_fail`` pin that.

P5.3 evidence is mandatory, not optional
---------------------------------------
``ProductProductionIntent.recipe_evidence`` is a
``RecipeSelectionEvidence``. The compiler obtains it by calling P6.4's
``VisualCompiler.bind()``, which is itself a single call to P5.3's
``retrieve_with_evidence()``. So a production intent cannot exist without a
selection decision recorded, and ``ProductCompiler`` never creates a
``RecipeSelector``, ``ShotSelector`` or ``MotionSelector`` of its own.

What this does not build
------------------------
No ``ShotPlan``. No ``MotionPlan``. No timeline. No ``RenderCommand``. Those are
P0/P1's and P6.6's. P6.5's output is the blueprint those consume: four intents,
one selection decision, and the constraints that bound production.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hevi.production.p5_3.library import RecipeLibrary
from hevi.production.p5_3.schema import RecipeSelectionEvidence
from hevi.production.p6.narrative.compiler import (
    NarrativeCompiler,
    NarrativeIntent,
)
from hevi.production.p6.narrative.registry import NARRATIVE_GRAMMAR_REGISTRY
from hevi.production.p6.presenter_compiler import PresenterCompiler, PresenterIntent
from hevi.production.p6.presenter_registry import (
    GRAMMAR_COMPATIBILITY_REGISTRY,
    PRESENTER_GRAMMAR_REGISTRY,
)
from hevi.production.p6.product_profiles import (
    COMMERCIAL_PRODUCT_REGISTRY,
    CommercialProductRegistry,
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

#: The four references a commercial profile must declare. Missing any one of
#: them is ``INVALID_PRODUCT_PROFILE`` — never a default.
REQUIRED_GRAMMAR_REFERENCES = (
    "narrative_grammar_id",
    "presenter_grammar_id",
    "visual_style_id",
    "visual_grammar_id",
)


def _dedupe(constraints: tuple[ProductConstraint, ...]) -> tuple[ProductConstraint, ...]:
    unique = {(c.key, c.value, c.rationale): c for c in constraints}
    return tuple(unique[k] for k in sorted(unique))


@dataclass(frozen=True)
class ProductProductionIntent:
    """A complete, filmable blueprint for one commercial product.

    Four compiled intents, one recorded selection decision, and the constraints
    that bound production. Deterministic by construction: every field is a
    frozen dataclass or a sorted constraint tuple, and ``content_hash()`` covers
    all of it.
    """

    product_id: str
    commercial_product: str
    product_type: str
    product_profile_version: str
    narrative_intent: NarrativeIntent
    presenter_intent: PresenterIntent
    visual_style_intent: VisualStyleIntent
    visual_intent: VisualIntent
    recipe_evidence: RecipeSelectionEvidence
    constraints: tuple[ProductConstraint, ...] = ()
    policy: tuple[tuple[str, str], ...] = ()

    @property
    def duration_policy(self) -> dict[str, float]:
        for key, value in self.policy:
            if key == "target_s":
                return {"target_s": float(value)}
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "commercial_product": self.commercial_product,
            "product_type": self.product_type,
            "product_profile_version": self.product_profile_version,
            "narrative_intent": self.narrative_intent.to_dict(),
            "presenter_intent": self.presenter_intent.to_dict(),
            "visual_style_intent": self.visual_style_intent.to_dict(),
            "visual_intent": self.visual_intent.to_dict(),
            "recipe_evidence": {
                # timestamp excluded: P5.3 documents identical evidence except for
                # it, and a plan whose hash moves every run cannot be diffed.
                k: v
                for k, v in self.recipe_evidence.to_dict().items()
                if k != "timestamp"
            },
            "constraints": [c.to_dict() for c in self.constraints],
            "policy": [list(pair) for pair in self.policy],
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def summary(self) -> str:
        """One human-readable line: the brief in, the blueprint out."""
        return (
            f"{self.commercial_product} "
            f"[{self.narrative_intent.grammar_id} + {self.presenter_intent.grammar_id} "
            f"+ {self.visual_style_intent.style_id} + {self.visual_intent.visual_grammar_id}] "
            f"-> {self.recipe_evidence.selected_recipe_id}"
        )


class ProductCompilationError(ValueError):
    """Raised when a production intent cannot be produced."""


@dataclass(frozen=True)
class ProductCompiler:
    """The single compiler for all commercial products.

    Holds sub-compilers, not product knowledge. Stateless: the same instance
    compiles any number of products, and compile order never affects a result.
    """

    registry: CommercialProductRegistry = COMMERCIAL_PRODUCT_REGISTRY
    narrative_compiler: NarrativeCompiler = field(
        default_factory=lambda: NarrativeCompiler(NARRATIVE_GRAMMAR_REGISTRY)
    )
    presenter_compiler: PresenterCompiler = field(
        default_factory=lambda: PresenterCompiler(
            PRESENTER_GRAMMAR_REGISTRY, GRAMMAR_COMPATIBILITY_REGISTRY
        )
    )
    visual_style_compiler: VisualStyleCompiler = field(
        default_factory=lambda: VisualStyleCompiler(
            VISUAL_STYLE_REGISTRY, STYLE_COMPATIBILITY_REGISTRY
        )
    )
    visual_compiler: VisualCompiler = field(
        default_factory=lambda: VisualCompiler(
            VISUAL_GRAMMAR_REGISTRY, VISUAL_GRAMMAR_COMPATIBILITY
        )
    )

    compiler_id = "p6_5_product_compiler"

    # ── profile resolution ────────────────────────────────────────────────

    def resolve_profile(self, product_id: str) -> ProductProfile:
        if not product_id or not product_id.strip():
            raise KeyError("UNKNOWN_PRODUCT_PROFILE:no product id supplied")
        return self.registry.resolve(product_id.strip())

    def list_products(self) -> list[str]:
        return self.registry.list_ids()

    # ── static validation ─────────────────────────────────────────────────

    def validate_profile(self, profile: ProductProfile) -> tuple[bool, list[str]]:
        """Structural checks only. No compilation, no product knowledge."""
        errors: list[str] = []
        missing = [
            name for name in REQUIRED_GRAMMAR_REFERENCES if not getattr(profile, name, "")
        ]
        if missing:
            errors.append(f"INVALID_PRODUCT_PROFILE:{'|'.join(missing)}")
        if not profile.grammars:
            errors.append("INVALID_PRODUCT_PROFILE:grammars")
        return (not errors), errors

    # ── compile ───────────────────────────────────────────────────────────

    def compile(
        self,
        product_id: str | ProductProfile,
        *,
        recipe_library: RecipeLibrary,
        beat_id: str = "",
        profile_id: str = "",
        duration: float | None = None,
        extra_constraints: tuple[ProductConstraint, ...] = (),
    ) -> ProductProductionIntent:
        """Compile one commercial product into a production intent.

        Fail-closed at every stage: an unknown profile, a profile missing a
        grammar reference, an unregistered grammar, an incoherent pairing, or a
        P5.3 retrieval that selects nothing all raise. There is no default
        profile, no default grammar and no default recipe anywhere on this path.
        """
        if isinstance(product_id, ProductProfile):
            profile = product_id
        else:
            try:
                profile = self.resolve_profile(product_id)
            except KeyError as exc:
                raise ProductCompilationError(str(exc)) from exc

        ok, errors = self.validate_profile(profile)
        if not ok:
            raise ProductCompilationError(";".join(errors))

        if recipe_library is None:
            # A plan without a recorded selection decision is not a plan.
            raise ProductCompilationError(
                "INVALID_PRODUCT_PROFILE:recipe_library required; a production "
                "intent cannot exist without P5.3 selection evidence"
            )

        # P6.1 — narrative.
        try:
            narrative = self.narrative_compiler.compile_with(
                profile, extra_constraints=extra_constraints
            )
        except Exception as exc:
            raise ProductCompilationError(f"NARRATIVE_INVALID:{profile.id}:{exc}") from exc

        # P6.2 — presenter, cross-checked against the narrative it will perform.
        try:
            presenter = self.presenter_compiler.compile_with(
                profile, narrative, extra_constraints=extra_constraints
            )
        except Exception as exc:
            raise ProductCompilationError(f"PRESENTER_INVALID:{profile.id}:{exc}") from exc

        # P6.3 — visual style, cross-checked against both upstream intents.
        try:
            style = self.visual_style_compiler.compile_product_intent(
                profile.id, narrative, presenter, profile.visual_style_id
            )
        except Exception as exc:
            raise ProductCompilationError(f"VISUAL_STYLE_INVALID:{profile.id}:{exc}") from exc

        # P6.4 — visual grammar, cross-checked against the style it must agree with.
        try:
            visual = self.visual_compiler.compile(
                narrative,
                presenter,
                self.visual_compiler.resolve_grammar(profile.visual_grammar_id),
                style=style,
            )
        except Exception as exc:
            raise ProductCompilationError(
                f"VISUAL_GRAMMAR_INVALID:{profile.id}:{exc}"
            ) from exc

        # P5.3 — the selection decision. Mandatory.
        try:
            binding = self.visual_compiler.bind(
                recipe_library,
                visual,
                beat_id=beat_id or f"{profile.id}#beat0",
                profile_id=profile_id,
                duration=duration,
            )
        except LookupError as exc:
            raise ProductCompilationError(f"P5_3_NO_RECIPE:{profile.id}:{exc}") from exc

        policy: tuple[tuple[str, str], ...] = ()
        if profile.duration_policy is not None:
            policy = (
                ("target_s", str(profile.duration_policy.target_s)),
                ("min_s", str(profile.duration_policy.min_s)),
                ("max_s", str(profile.duration_policy.max_s)),
            )
        policy = (*policy, ("aspect", profile.aspect_policy.value))

        return ProductProductionIntent(
            product_id=profile.id,
            commercial_product=profile.id,
            product_type=profile.product_type.value,
            product_profile_version=profile.version,
            narrative_intent=narrative,
            presenter_intent=presenter,
            visual_style_intent=style,
            visual_intent=visual,
            recipe_evidence=binding.evidence,
            constraints=_dedupe(
                extra_constraints
                + narrative.constraints
                + presenter.constraints
                + style.constraints
                + visual.constraints
            ),
            policy=policy,
        )

    def compile_all(
        self,
        *,
        recipe_library: RecipeLibrary,
        **kwargs: Any,
    ) -> list[ProductProductionIntent]:
        """Compile every registered product, in id order."""
        return [
            self.compile(product_id, recipe_library=recipe_library, **kwargs)
            for product_id in self.registry.list_ids()
        ]


__all__ = [
    "REQUIRED_GRAMMAR_REFERENCES",
    "ProductCompilationError",
    "ProductCompiler",
    "ProductProductionIntent",
]
