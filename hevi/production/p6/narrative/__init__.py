"""HEVI P6.1 — Narrative grammar.

The first P6 grammar with working behaviour:

    ProductProfile.narrative_grammar_id
        -> NARRATIVE_GRAMMAR_REGISTRY
        -> NarrativeCompiler
        -> NarrativeIntent
        -> ProductIntent (via compile_product_intent)

Four general built-in shapes ship: ``explanatory``, ``documentary``, ``story``,
``short_form``. None is product-specific — a product composes these rather than
owning a private shape, which is what keeps ten products on one engine.

P6.1 is narrative *intent*. It emits an ordered node sequence. It does not
emit ``VisualBeat``, ``ShotPlan`` or ``MotionPlan``, does not select a renderer,
does not acquire assets, and does not judge quality. Those authorities are
unchanged and unimported.
"""

from hevi.production.p6.narrative.builtin import (
    BUILTIN_NARRATIVE_GRAMMARS,
    DOCUMENTARY,
    EXPLANATORY,
    SHORT_FORM,
    STORY,
    register_builtin_grammars,
)
from hevi.production.p6.narrative.compiler import (
    NarrativeCompilationError,
    NarrativeCompiler,
    NarrativeIntent,
    NarrativeValidationResult,
)
from hevi.production.p6.narrative.model import (
    NarrativeGrammar,
    NarrativeNode,
    NarrativeNodeType,
    NarrativeTransition,
)
from hevi.production.p6.narrative.registry import (
    NARRATIVE_GRAMMAR_REGISTRY,
    NarrativeGrammarRegistry,
)

__all__ = [
    "BUILTIN_NARRATIVE_GRAMMARS",
    "DOCUMENTARY",
    "EXPLANATORY",
    "NARRATIVE_GRAMMAR_REGISTRY",
    "NarrativeCompilationError",
    "NarrativeCompiler",
    "NarrativeGrammar",
    "NarrativeGrammarRegistry",
    "NarrativeIntent",
    "NarrativeNode",
    "NarrativeNodeType",
    "NarrativeTransition",
    "NarrativeValidationResult",
    "SHORT_FORM",
    "STORY",
    "register_builtin_grammars",
]
