"""HEVI P6.3 — Visual style compiler.

Consumes the two upstream P6 intents plus a visual style grammar, and produces a
``VisualStyleIntent``. It is the third stage in the chain:

    ProductProfile
      → NarrativeCompiler  → NarrativeIntent
      → PresenterCompiler  → PresenterIntent
      → VisualStyleCompiler → VisualStyleIntent
      → ProductIntent

What the presenter contributes
------------------------------
``PresenterIntent`` is not decoration here — Phase 4 makes it an input for a
reason. A performance shape constrains the composition that can carry it:
an avatar explainer or a lecture cannot be framed as an observed documentary.
That rule is ``COMPOSITION_COMPATIBILITY`` in the registry module: data, keyed by
presenter grammar id, listing the composition languages able to carry that
performance. So the presenter genuinely narrows the style choice, and the second
refusal path is declarative rather than a branch.

Why compatibility has two dimensions
------------------------------------
1. narrative → style: which looks may serve which arc
   (``STYLE_COMPATIBILITY_REGISTRY``).
2. presenter → composition: which frames may carry which performance
   (``COMPOSITION_COMPATIBILITY``).

Both surface as ``INCOMPATIBLE_STYLE_PAIRING`` but they are distinct defects with
distinct reasons, so the error carries a human-readable ``detail`` explaining
which pairing was incoherent and why. A future caller can act on the reason.

Determinism
-----------
No clock, no RNG, no environment read, no unordered-set iteration. Constraints are
merged then sorted by ``(key, value, rationale)``, so two runs over the same input
produce a byte-identical ``content_hash()``.

Not an authority
----------------
Names no renderer, asset generator, image model, provider, timeline or shot. The
output declares qualities; what executes them is the existing downstream
authority, unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from hevi.production.p6.narrative.compiler import NarrativeIntent
from hevi.production.p6.presenter_compiler import PresenterIntent
from hevi.production.p6.schema import ProductConstraint
from hevi.production.p6.visual_style.model import (
    ColorLanguage,
    CompositionLanguage,
    LightingLanguage,
    Mood,
    MotionLanguage,
    TextureLanguage,
    VisualStyleGrammar,
)
from hevi.production.p6.visual_style.registry import (
    COMPOSITION_COMPATIBILITY,
    STYLE_COMPATIBILITY_REGISTRY,
    VISUAL_STYLE_REGISTRY,
    StyleCompatibilityRegistry,
    VisualStyleRegistry,
)

_RESERVED_PREFIX = "visual_style:"


def _strip_reserved(constraint: ProductConstraint) -> ProductConstraint | None:
    """Drop inherited P6.0/P6.1/P6.2 style-free visual keys if re-declared.

    Keeps the style layer's constraint set unambiguous: every key that survives
    here is either declared by the style grammar or inherited from the
    presenter's declared visual requirements.
    """
    if constraint.key.startswith(_RESERVED_PREFIX):
        return None
    return constraint


def _dedupe(constraints: tuple[ProductConstraint, ...]) -> tuple[ProductConstraint, ...]:
    """Deterministically deduplicate on the full triple, then sort."""
    unique = {(c.key, c.value, c.rationale): c for c in constraints}
    return tuple(unique[k] for k in sorted(unique))


@dataclass(frozen=True)
class VisualStyleValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors)}


@dataclass(frozen=True)
class VisualStyleIntent:
    """Compiled visual style intent for one product.

    Carries the six resolved visual languages plus the constraints that must hold
    when they are realised. Holds no renderer, provider, asset, timeline, shot or
    pixel value: this is intent, and the existing authorities execute it.
    """

    style_id: str
    style_version: str
    product_profile_id: str
    narrative_grammar_id: str = ""
    presenter_grammar_id: str = ""
    category: str = ""
    mood: Mood = Mood.MINIMAL
    palette: ColorLanguage = ColorLanguage.NATURAL
    composition: CompositionLanguage = CompositionLanguage.DOCUMENTARY
    texture: TextureLanguage = TextureLanguage.REALISTIC
    motion: MotionLanguage = MotionLanguage.RESTRAINED
    lighting: LightingLanguage = LightingLanguage.NATURAL
    constraints: tuple[ProductConstraint, ...] = ()
    inherited_requirements: tuple[ProductConstraint, ...] = ()
    validation_result: VisualStyleValidationResult = field(
        default_factory=lambda: VisualStyleValidationResult(valid=False)
    )

    @property
    def qualified_style_id(self) -> str:
        return f"{self.style_id}@v{self.style_version}"

    def languages(self) -> dict[str, str]:
        return {
            "mood": self.mood.value,
            "palette": self.palette.value,
            "composition": self.composition.value,
            "texture": self.texture.value,
            "motion": self.motion.value,
            "lighting": self.lighting.value,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_id": self.style_id,
            "style_version": self.style_version,
            "product_profile_id": self.product_profile_id,
            "narrative_grammar_id": self.narrative_grammar_id,
            "presenter_grammar_id": self.presenter_grammar_id,
            "category": self.category,
            "mood": self.mood.value,
            "palette": self.palette.value,
            "composition": self.composition.value,
            "texture": self.texture.value,
            "motion": self.motion.value,
            "lighting": self.lighting.value,
            "constraints": [c.to_dict() for c in self.constraints],
            "inherited_requirements": [c.to_dict() for c in self.inherited_requirements],
            "validation_result": self.validation_result.to_dict(),
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class VisualStyleCompiler:
    """Compiles a visual style grammar into intent for a specific product.

    Stateless and reusable: the same instance compiles any number of products
    identically, and no per-compile state survives a call.
    """

    compiler_id = "p6_3_visual_style"

    def __init__(
        self,
        registry: VisualStyleRegistry | None = None,
        compatibility: StyleCompatibilityRegistry | None = None,
    ) -> None:
        self._registry = registry if registry is not None else VISUAL_STYLE_REGISTRY
        self._compatibility = (
            compatibility if compatibility is not None else STYLE_COMPATIBILITY_REGISTRY
        )

    # ── resolution ────────────────────────────────────────────────────────

    def resolve_style(
        self, style_id: str, version: str | None = None
    ) -> VisualStyleGrammar:
        """Resolve a style reference or raise. Never returns a default.

        A missing reference and an unregistered reference are *different*
        defects: ``VISUAL_STYLE_NOT_FOUND`` means the profile named no style,
        ``UNKNOWN_VISUAL_STYLE`` means it named one that does not exist. Both
        fail closed; neither silently substitutes anything.
        """
        if not style_id or not style_id.strip():
            raise KeyError("VISUAL_STYLE_NOT_FOUND:profile declares no visual_style_id")
        style = self._registry.get(style_id.strip(), version)
        if style is None:
            raise KeyError(f"UNKNOWN_VISUAL_STYLE:{style_id}")
        return style

    # ── compatibility ─────────────────────────────────────────────────────

    def check_compatibility(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        style: VisualStyleGrammar,
    ) -> tuple[bool, list[str]]:
        """Two independent pairing checks. Both must hold."""
        errors: list[str] = []
        narrative_id = narrative.grammar_id

        permitted = self._compatibility.allowed(narrative_id)
        if permitted is not None and style.id not in permitted:
            errors.append(
                f"INCOMPATIBLE_STYLE_PAIRING:narrative={narrative_id}"
                f":style={style.id}:permitted={'|'.join(sorted(permitted))}"
            )

        # Presenter → composition. A performed shape needs a frame built for a
        # performer; an observed frame cannot carry one without contradicting it.
        allowed_compositions = COMPOSITION_COMPATIBILITY.get(presenter.grammar_id)
        if (
            allowed_compositions is not None
            and style.composition_language not in allowed_compositions
        ):
            errors.append(
                f"INCOMPATIBLE_STYLE_PAIRING:presenter={presenter.grammar_id}"
                f":composition={style.composition_language.value}"
                f":permitted={'|'.join(sorted(c.value for c in allowed_compositions))}"
            )

        return (not errors), errors

    # ── validation ────────────────────────────────────────────────────────

    def validate(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        style: VisualStyleGrammar,
    ) -> tuple[bool, list[str]]:
        ok, grammar_errors = self._registry.validate(style.id, style.version)
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

        ok_pair, pair_errors = self.check_compatibility(narrative, presenter, style)
        if not ok_pair:
            errors.extend(pair_errors)

        for channel, value in sorted(style.languages().items()):
            if not value:
                errors.append(f"EMPTY_STYLE_LANGUAGE:{channel}")

        return (not errors), errors

    # ── compile ───────────────────────────────────────────────────────────

    def compile(
        self,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        style: VisualStyleGrammar,
    ) -> VisualStyleIntent:
        """Compile one product's visual style intent.

        Raises on any incoherence. There is no ``try_compile`` escape hatch that
        returns a partial intent, because a partially-styled intent is exactly
        the kind of thing a downstream renderer would silently execute.
        """
        ok, errors = self.validate(narrative, presenter, style)
        if not ok:
            raise ValueError(";".join(errors))

        declared = tuple(
            kept
            for c in style.constraints
            if (kept := _strip_reserved(c)) is not None
        )
        # The presenter's declared visual needs are inherited, not reinterpreted:
        # the style layer must not weaken what the performance already requires.
        inherited = tuple(
            kept
            for c in presenter.visual_requirements
            if (kept := _strip_reserved(c)) is not None
        )

        return VisualStyleIntent(
            style_id=style.id,
            style_version=style.version,
            product_profile_id=narrative.product_profile_id,
            narrative_grammar_id=narrative.grammar_id,
            presenter_grammar_id=presenter.grammar_id,
            category=style.category.value,
            mood=style.mood,
            palette=style.color_language,
            composition=style.composition_language,
            texture=style.texture_language,
            motion=style.motion_language,
            lighting=style.lighting_language,
            constraints=_dedupe(declared),
            inherited_requirements=_dedupe(inherited),
            validation_result=VisualStyleValidationResult(valid=True),
        )

    def compile_product_intent(
        self,
        product_profile_id: str,
        narrative: NarrativeIntent,
        presenter: PresenterIntent,
        style_id: str = "",
        version: str | None = None,
    ) -> VisualStyleIntent:
        """Convenience entry point resolving the style by reference."""
        style = self.resolve_style(style_id, version)
        return self.compile(narrative, presenter, style)

    # ── introspection ─────────────────────────────────────────────────────

    def list_compatible_styles(
        self, narrative: NarrativeIntent, presenter: PresenterIntent
    ) -> list[str]:
        """Every registered style that compiles cleanly for this pair.

        Useful for diagnostics and for tests sweeping the full pairing matrix;
        the compiler itself never consults this to pick a fallback.
        """
        usable: list[str] = []
        for style in sorted(self._registry.list_all(), key=lambda s: s.qualified_id):
            ok, _ = self.check_compatibility(narrative, presenter, style)
            if ok and self.validate(narrative, presenter, style)[0]:
                usable.append(style.id)
        return usable


__all__ = [
    "VisualStyleCompiler",
    "VisualStyleIntent",
    "VisualStyleValidationResult",
]
