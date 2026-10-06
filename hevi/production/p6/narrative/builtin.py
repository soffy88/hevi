"""HEVI P6.1 — Built-in narrative grammars.

Four general shapes, usable by any product. None is product-specific: a
commercial can use ``explanatory``, a documentary can use ``story``, and a
short-form explainer can use ``explanatory`` with ``pattern_interrupt``
included.

What is deliberately absent: no ``commercial.*``, ``historical.*`` or
``product.*`` grammar. A product is defined by *which* of these general shapes
it composes, not by owning a private shape. That is what keeps ten products on
one engine — a private grammar per product is a private pipeline per product in
all but name.

Registered into :data:`NARRATIVE_GRAMMAR_REGISTRY` on import of this module, so
the built-ins are available without a caller-side bootstrap step.
"""

from __future__ import annotations

from hevi.production.p6.narrative.model import (
    NarrativeGrammar,
    NarrativeNode,
    NarrativeNodeType,
    NarrativeTransition,
)
from hevi.production.p6.narrative.registry import NARRATIVE_GRAMMAR_REGISTRY
from hevi.production.p6.schema import ProductConstraint

_T = NarrativeNodeType


def _n(node_id: str, node_type: NarrativeNodeType, order: int, *, optional: bool = False) -> NarrativeNode:
    return NarrativeNode(
        id=node_id, type=node_type, order=order, required=not optional, optional=optional
    )


EXPLANATORY = NarrativeGrammar(
    id="explanatory",
    version="1.0.0",
    name="Explanatory",
    description=(
        "Open with a hook, establish context, explain, show the explanation "
        "happening, then close. The general shape for teaching content."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0),
        _n("context", _T.CONTEXT, 1),
        _n("explanation", _T.EXPLANATION, 2),
        _n("demonstration", _T.DEMONSTRATION, 3),
        _n("conclusion", _T.CONCLUSION, 4),
    ),
    transitions=(
        NarrativeTransition("hook", "context", "earn attention before orienting"),
        NarrativeTransition("context", "explanation", "orient before explaining"),
        NarrativeTransition("explanation", "demonstration", "show what was explained"),
        NarrativeTransition("demonstration", "conclusion", "land the point"),
    ),
    constraints=(
        ProductConstraint(
            key="min_nodes", value="5", rationale="an explanation needs all five stages"
        ),
        ProductConstraint(
            key="demonstration_required",
            value="true",
            rationale="an explained idea that is never shown is asserted, not taught",
        ),
    ),
)


DOCUMENTARY = NarrativeGrammar(
    id="documentary",
    version="1.0.0",
    name="Documentary",
    description=(
        "Hook, orient, present evidence, develop it, interpret it, close. "
        "Separates what is shown from what is concluded, which is what makes a "
        "documentary honest."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0),
        _n("context", _T.CONTEXT, 1),
        _n("evidence", _T.EVIDENCE, 2),
        _n("development", _T.DEVELOPMENT, 3),
        _n("interpretation", _T.INTERPRETATION, 4),
        _n("conclusion", _T.CONCLUSION, 5),
    ),
    transitions=(
        NarrativeTransition("hook", "context", "earn attention before orienting"),
        NarrativeTransition("context", "evidence", "orient before showing proof"),
        NarrativeTransition("evidence", "development", "develop what the evidence shows"),
        NarrativeTransition("development", "interpretation", "separate shown from concluded"),
        NarrativeTransition("interpretation", "conclusion", "close on the reading"),
    ),
    constraints=(
        ProductConstraint(
            key="evidence_before_interpretation",
            value="true",
            rationale="interpretation before evidence is assertion",
        ),
        ProductConstraint(
            key="min_nodes", value="6", rationale="documentary needs evidence and interpretation"
        ),
    ),
)


STORY = NarrativeGrammar(
    id="story",
    version="1.0.0",
    name="Story",
    description=(
        "Hook, set up, conflict, turn, resolve, close. The general dramatic arc, "
        "usable by fiction and by any product with a problem to solve."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0),
        _n("setup", _T.SETUP, 1),
        _n("conflict", _T.CONFLICT, 2),
        _n("turning_point", _T.TURNING_POINT, 3),
        _n("resolution", _T.RESOLUTION, 4),
        _n("conclusion", _T.CONCLUSION, 5),
    ),
    transitions=(
        NarrativeTransition("hook", "setup", "promise before context"),
        NarrativeTransition("setup", "conflict", "stakes before obstruction"),
        NarrativeTransition("conflict", "turning_point", "obstruction before turn"),
        NarrativeTransition("turning_point", "resolution", "turn before resolution"),
        NarrativeTransition("resolution", "conclusion", "land before closing"),
    ),
    constraints=(
        ProductConstraint(
            key="conflict_required", value="true", rationale="a story without stakes is a scene"
        ),
        ProductConstraint(
            key="turning_point_required",
            value="true",
            rationale="without a turn the arc is a list of events",
        ),
    ),
)


SHORT_FORM = NarrativeGrammar(
    id="short_form",
    version="1.0.0",
    name="Short Form",
    description=(
        "Hook, break the pattern, develop, pay off, act. PATTERN_INTERRUPT is a "
        "general device — it names breaking an established expectation at any "
        "length — not a short-form-only runtime branch."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0),
        _n("pattern_interrupt", _T.PATTERN_INTERRUPT, 1),
        _n("development", _T.DEVELOPMENT, 2),
        _n("payoff", _T.PAYOFF, 3),
        _n("cta", _T.CTA, 4),
    ),
    transitions=(
        NarrativeTransition("hook", "pattern_interrupt", "promise then break it"),
        NarrativeTransition("pattern_interrupt", "development", "break then develop"),
        NarrativeTransition("development", "payoff", "deliver what was promised"),
        NarrativeTransition("payoff", "cta", "reward then ask"),
    ),
    constraints=(
        ProductConstraint(
            key="pattern_interrupt_required",
            value="true",
            rationale="without an interrupt the hook has nothing to interrupt",
        ),
        ProductConstraint(
            key="hook_and_payoff_required",
            value="true",
            rationale="a payoff without a hook is unearned",
        ),
    ),
)


#: Every built-in grammar, in registration order.
BUILTIN_NARRATIVE_GRAMMARS: tuple[NarrativeGrammar, ...] = (
    EXPLANATORY,
    DOCUMENTARY,
    STORY,
    SHORT_FORM,
)


def register_builtin_grammars(*, force: bool = False) -> list[str]:
    """Register the built-ins. Idempotent.

    ``force`` re-registers after a registry reset, which is what a test needing
    a clean registry wants. It never overwrites silently: if a grammar with the
    same ``id@version`` is already present with *different* content, the
    immutable guard raises rather than replacing it.
    """
    registered: list[str] = []
    for grammar in BUILTIN_NARRATIVE_GRAMMARS:
        existing = NARRATIVE_GRAMMAR_REGISTRY.get(grammar.id, grammar.version)
        if existing is not None and not force:
            registered.append(grammar.qualified_id)
            continue
        if existing is not None and existing.content_hash() != grammar.content_hash():
            raise ValueError(
                f"NARRATIVE_GRAMMAR_IMMUTABLE:{grammar.qualified_id} already registered "
                "with different content"
            )
        NARRATIVE_GRAMMAR_REGISTRY.register(grammar)
        registered.append(grammar.qualified_id)
    return registered


register_builtin_grammars()


__all__ = [
    "BUILTIN_NARRATIVE_GRAMMARS",
    "DOCUMENTARY",
    "EXPLANATORY",
    "SHORT_FORM",
    "STORY",
    "register_builtin_grammars",
]
