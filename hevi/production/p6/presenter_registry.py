"""HEVI P6.2 — Presenter registry, built-ins and grammar compatibility.

Three authorities live here, and each answers one question:

``PRESENTER_GRAMMAR_REGISTRY``
    "What is an avatar explainer performance?" — holds
    :class:`~hevi.production.p6.presenter.PresenterGrammar` definitions.

``GRAMMAR_COMPATIBILITY_REGISTRY``
    "Which presenters may perform a given narrative?" — the declarative table
    that closes the P6.1 gap where a profile could declare a narrative and a
    presenter that had nothing to do with each other.

``BUILTIN_PRESENTER_GRAMMARS``
    The shipped general shapes. No product-named grammar: a product *selects* a
    presenter, it does not own one.

Why compatibility is a table and not a check in the compiler
------------------------------------------------------------
The alternative — ``if narrative == "documentary" and presenter == "avatar"`` —
is exactly the per-product branching this architecture forbids. A table keyed by
grammar id lets the rule be data, so adding a pairing is a data change and the
branching guard stays green.

Not an authority
----------------
Nothing here selects a provider, a voice, a camera, or a renderer.
``hevi.providers`` and ``hevi.renderers`` are untouched and unimported.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p6.presenter import (
    PresenterGrammar,
    PresenterNode,
    PresenterNodeType,
    PresenterRequirements,
)
from hevi.production.p6.schema import ProductConstraint

_T = PresenterNodeType


# ── Built-in presenter grammars ─────────────────────────────────────────


def _n(
    node_id: str,
    node_type: PresenterNodeType,
    order: int,
    purpose: str,
    *,
    required: bool = True,
) -> PresenterNode:
    return PresenterNode(
        id=node_id, type=node_type, purpose=purpose, order=order, required=required
    )


AVATAR_EXPLAINER = PresenterGrammar(
    id="avatar_explainer",
    version="1.0.0",
    name="Avatar Explainer",
    description=(
        "A synthetic or human stand-in earns attention, establishes who is "
        "speaking, explains, shows the explanation happening, then closes and "
        "asks. The general shape for anything a presenter delivers directly."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0, "earn attention before anything is asked of the viewer"),
        _n("identity", _T.IDENTITY, 1, "establish who is speaking and why they are credible"),
        _n("explanation", _T.EXPLANATION, 2, "deliver the explanation"),
        _n("demonstration", _T.DEMONSTRATION, 3, "show the explanation happening"),
        _n("conclusion", _T.CONCLUSION, 4, "land the point"),
        _n("cta", _T.CTA, 5, "ask for the action the video exists to produce"),
    ),
    requirements=PresenterRequirements(
        presentation_style="direct_address",
        speaker_requirements=(
            ProductConstraint(key="delivery", value="direct_address", rationale="the presenter addresses the viewer"),
            ProductConstraint(key="credibility_signal", value="required", rationale="a presenter must be legible as a source"),
        ),
        visual_requirements=(
            ProductConstraint(key="speaker_visibility", value="present", rationale="delivery is the point"),
        ),
        audio_requirements=(
            ProductConstraint(key="voice_required", value="true", rationale="explanation is spoken"),
        ),
    ),
    constraints=(
        ProductConstraint(key="min_nodes", value="6", rationale="a direct delivery needs all six beats"),
        ProductConstraint(key="identity_required", value="true", rationale="an uncredited presenter is a voice, not a source"),
    ),
)


DOCUMENTARY_EXPLAINER = PresenterGrammar(
    id="documentary_explainer",
    version="1.0.0",
    name="Documentary Explainer",
    description=(
        "A narrator or presenter earns attention, orients, presents evidence, "
        "explains it, interprets it, and closes. Separates what is shown from "
        "what is concluded."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0, "earn attention before orienting"),
        _n("context", _T.CONTEXT, 1, "orient the viewer in subject and time"),
        _n("evidence", _T.EVIDENCE, 2, "present what supports the claim"),
        _n("explanation", _T.EXPLANATION, 3, "explain what the evidence shows"),
        _n("interpretation", _T.INTERPRETATION, 4, "separate what is shown from what is concluded"),
        _n("conclusion", _T.CONCLUSION, 5, "close on the reading"),
    ),
    requirements=PresenterRequirements(
        presentation_style="documentary_narration",
        speaker_requirements=(
            ProductConstraint(key="delivery", value="narration", rationale="the presenter narrates rather than performs"),
        ),
        visual_requirements=(
            ProductConstraint(key="evidence_visibility", value="required", rationale="the claim rests on what is shown"),
        ),
        audio_requirements=(
            ProductConstraint(key="voice_required", value="true", rationale="narration is the spine"),
        ),
    ),
    constraints=(
        ProductConstraint(key="min_nodes", value="6", rationale="evidence and interpretation are both required"),
        ProductConstraint(
            key="evidence_before_interpretation",
            value="true",
            rationale="interpreting before showing is assertion",
        ),
    ),
)


HISTORICAL_RECONSTRUCTION = PresenterGrammar(
    id="historical_reconstruction",
    version="1.0.0",
    name="Historical Reconstruction",
    description=(
        "A performer becomes the historical figure, narrates the events, and the "
        "evidence is held apart from the reconstruction. The presentation must "
        "never let a reconstruction read as a record."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0, "earn attention before entering the period"),
        _n("context", _T.CONTEXT, 1, "establish era and situation"),
        _n("character", _T.CHARACTER, 2, "establish who is being reconstructed"),
        _n("event", _T.EVENT, 3, "narrate what happened"),
        _n("evidence", _T.EVIDENCE, 4, "support the account with what is documented"),
        _n("interpretation", _T.INTERPRETATION, 5, "mark the reading as reading"),
        _n("conclusion", _T.CONCLUSION, 6, "close without implying the record is complete"),
    ),
    requirements=PresenterRequirements(
        presentation_style="historical_reconstruction",
        speaker_requirements=(
            ProductConstraint(key="delivery", value="in_character_narrated", rationale="the performance and the narration are distinguished"),
            ProductConstraint(key="identity_continuity", value="required", rationale="the figure must stay the same figure"),
        ),
        visual_requirements=(
            ProductConstraint(key="reconstruction_disclosure", value="required", rationale="a reconstruction must read as a reconstruction"),
        ),
        audio_requirements=(
            ProductConstraint(key="voice_required", value="true", rationale="the account is spoken"),
        ),
    ),
    constraints=(
        ProductConstraint(key="min_nodes", value="7", rationale="character, event and evidence are all required"),
        ProductConstraint(
            key="evidence_before_interpretation",
            value="true",
            rationale="a reconstruction unsupported by evidence is fiction",
        ),
        ProductConstraint(
            key="reconstruction_disclosure_required",
            value="true",
            rationale="the viewer must be able to tell what is reconstructed",
        ),
    ),
)


EDUCATIONAL_LECTURE = PresenterGrammar(
    id="educational_lecture",
    version="1.0.0",
    name="Educational Lecture",
    description=(
        "A lecturer earns attention, establishes authority, teaches, checks "
        "understanding, and closes. General to instruction, not to any subject."
    ),
    nodes=(
        _n("hook", _T.HOOK, 0, "earn attention with the problem worth solving"),
        _n("authority", _T.AUTHORITY, 1, "establish why this presenter is worth listening to"),
        _n("explanation", _T.EXPLANATION, 2, "teach the concept"),
        _n("demonstration", _T.DEMONSTRATION, 3, "show the concept applied"),
        _n("conclusion", _T.CONCLUSION, 4, "consolidate"),
        _n("cta", _T.CTA, 5, "point at the next step"),
    ),
    requirements=PresenterRequirements(
        presentation_style="instructional_delivery",
        speaker_requirements=(
            ProductConstraint(key="delivery", value="instructive", rationale="the presenter teaches rather than sells"),
            ProductConstraint(key="credibility_signal", value="required", rationale="instruction rests on the source's standing"),
        ),
        visual_requirements=(
            ProductConstraint(key="demonstration_visibility", value="required", rationale="a concept never shown is asserted"),
        ),
        audio_requirements=(
            ProductConstraint(key="voice_required", value="true", rationale="the teaching is spoken"),
        ),
    ),
    constraints=(
        ProductConstraint(key="min_nodes", value="6", rationale="authority and demonstration are both required"),
        ProductConstraint(key="authority_required", value="true", rationale="instruction without standing is just assertion"),
    ),
)


PRODUCT_PRESENTATION = PresenterGrammar(
    id="product_presentation",
    version="1.0.0",
    name="Product Presentation",
    description=(
        "A presenter introduces a product, shows real evidence of it working, "
        "demonstrates, and closes. The evidence requirement is what keeps this "
        "from becoming a promise."
    ),
    nodes=(
        _n("intro", _T.INTRO, 0, "introduce what is being shown"),
        _n("explanation", _T.EXPLANATION, 1, "state what it does"),
        _n("evidence", _T.EVIDENCE, 2, "show it actually working"),
        _n("demonstration", _T.DEMONSTRATION, 3, "demonstrate the capability"),
        _n("conclusion", _T.CONCLUSION, 4, "land the value"),
        _n("cta", _T.CTA, 5, "ask for the action"),
    ),
    requirements=PresenterRequirements(
        presentation_style="direct_address",
        speaker_requirements=(
            ProductConstraint(key="delivery", value="direct_address", rationale="the presenter addresses the viewer"),
            ProductConstraint(key="claim_grounding", value="required", rationale="every claim must rest on shown evidence"),
        ),
        visual_requirements=(
            ProductConstraint(key="evidence_visibility", value="required", rationale="a product claim needs proof on screen"),
            ProductConstraint(key="product_identity_lock", value="required", rationale="the shown product must be the actual product"),
        ),
        audio_requirements=(
            ProductConstraint(key="voice_required", value="true", rationale="the claims are spoken"),
        ),
    ),
    constraints=(
        ProductConstraint(key="min_nodes", value="6", rationale="evidence and demonstration are both required"),
        ProductConstraint(key="evidence_required", value="true", rationale="a presentation with no evidence is a promise"),
        ProductConstraint(
            key="claim_grounding_required",
            value="true",
            rationale="an ungrounded claim is a compliance failure, not a style choice",
        ),
    ),
)


#: Every built-in presenter grammar, in registration order.
BUILTIN_PRESENTER_GRAMMARS: tuple[PresenterGrammar, ...] = (
    AVATAR_EXPLAINER,
    DOCUMENTARY_EXPLAINER,
    HISTORICAL_RECONSTRUCTION,
    EDUCATIONAL_LECTURE,
    PRODUCT_PRESENTATION,
)


# ── Presenter registry ──────────────────────────────────────────────────


def _split_qualified(ref: str) -> tuple[str, str | None]:
    """Split ``id@version``. Accepts ``id@1.0.0`` and ``id@v1.0.0``."""
    if "@" not in ref:
        return ref, None
    base, _, version = ref.partition("@")
    if not base or not version:
        return ref, None
    if version.startswith("v") and len(version) > 1:
        version = version[1:]
    return base, version


def _version_sort_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in version.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            return (0, *parts, 0)
    return tuple(parts)


class PresenterGrammarRegistry:
    """Single authority for presenter grammar definitions."""

    def __init__(self) -> None:
        self._grammars: dict[str, PresenterGrammar] = {}
        self._versions: dict[str, list[str]] = {}

    @staticmethod
    def _key(grammar_id: str, version: str) -> str:
        return f"{grammar_id}@v{version}"

    def register(self, grammar: PresenterGrammar) -> PresenterGrammar:
        if not isinstance(grammar, PresenterGrammar):
            raise ValueError(f"NOT_A_PRESENTER_GRAMMAR:{type(grammar).__name__}")
        key = grammar.qualified_id
        if key in self._grammars:
            raise ValueError(f"PRESENTER_GRAMMAR_IMMUTABLE:{key} already registered")
        self._grammars[key] = grammar
        self._versions.setdefault(grammar.id, []).append(grammar.version)
        return grammar

    def get(self, ref: str, version: str | None = None) -> PresenterGrammar | None:
        grammar_id, embedded = _split_qualified(ref)
        target = version or embedded
        if target:
            direct = self._grammars.get(self._key(grammar_id, target))
            if direct is not None:
                return direct
            stripped = target[1:] if target.startswith("v") else None
            if stripped:
                return self._grammars.get(self._key(grammar_id, stripped))
            return None
        versions = self._versions.get(grammar_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=_version_sort_key)[-1]
        return self._grammars.get(self._key(grammar_id, latest))

    def resolve(self, ref: str, version: str | None = None) -> PresenterGrammar:
        """Resolve or raise. A missing grammar is a defect, not an empty result."""
        grammar_id, embedded = _split_qualified(ref)
        grammar = self.get(grammar_id, version or embedded)
        if grammar is None:
            raise KeyError(f"UNKNOWN_PRESENTER_GRAMMAR:{ref}")
        return grammar

    def list_all(self) -> list[PresenterGrammar]:
        """Every registered grammar, across all ids and versions."""
        return list(self._grammars.values())

    def list_ids(self) -> list[str]:
        return sorted(self._versions)

    def list_versions(self, grammar_id: str) -> list[str]:
        return list(self._versions.get(grammar_id, []))

    def has(self, ref: str, version: str | None = None) -> bool:
        return self.get(ref, version) is not None

    def validate(self, ref: str, version: str | None = None) -> tuple[bool, list[str]]:
        grammar = self.get(ref, version)
        if grammar is None:
            return False, [f"PRESENTER_GRAMMAR_NOT_FOUND:{ref}"]
        errors: list[str] = []
        node_ids = [n.id for n in grammar.nodes]
        if len(set(node_ids)) != len(node_ids):
            errors.append("DUPLICATE_PRESENTER_NODE_ID")
        orders = [n.order for n in grammar.nodes]
        if len(set(orders)) != len(orders):
            errors.append("AMBIGUOUS_PRESENTER_NODE_ORDER")
        if not grammar.required_node_ids():
            errors.append("PRESENTER_GRAMMAR_WITHOUT_REQUIRED_NODE")
        if not grammar.sequence():
            errors.append("EMPTY_PRESENTER_SEQUENCE")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for grammar_id in self.list_ids():
            ok, grammar_errors = self.validate(grammar_id)
            if not ok:
                errors.extend(f"{grammar_id}:{e}" for e in grammar_errors)
        return (not errors), errors

    def stats(self) -> dict[str, Any]:
        return {
            "total_grammars": len(self._grammars),
            "distinct_ids": len(self._versions),
            "ids": self.list_ids(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {key: g.to_dict() for key, g in sorted(self._grammars.items())}


#: The single presenter grammar authority.
PRESENTER_GRAMMAR_REGISTRY = PresenterGrammarRegistry()


def register_builtin_presenter_grammars(*, force: bool = False) -> list[str]:
    """Register the built-ins. Idempotent, and never overwrites silently."""
    registered: list[str] = []
    for grammar in BUILTIN_PRESENTER_GRAMMARS:
        existing = PRESENTER_GRAMMAR_REGISTRY.get(grammar.id, grammar.version)
        if existing is not None and not force:
            registered.append(grammar.qualified_id)
            continue
        if existing is not None and existing.content_hash() != grammar.content_hash():
            raise ValueError(
                f"PRESENTER_GRAMMAR_IMMUTABLE:{grammar.qualified_id} already registered "
                "with different content"
            )
        PRESENTER_GRAMMAR_REGISTRY.register(grammar)
        registered.append(grammar.qualified_id)
    return registered


register_builtin_presenter_grammars()


# ── Grammar compatibility ───────────────────────────────────────────────


class GrammarCompatibilityRegistry:
    """Which presenter grammars may perform a given narrative grammar.

    This is the P6.1 gap closed as data. ``narrative=documentary`` with
    ``presenter=avatar_explainer`` is refused because the table does not list it
    — not because a conditional says so.

    Keyed by narrative grammar id, mapping to the set of permitted presenter
    grammar ids. A narrative absent from the table permits every registered
    presenter, which keeps a newly added narrative usable without a
    compatibility edit while still catching the pairings that are actually
    incoherent.
    """

    def __init__(self) -> None:
        self._table: dict[str, frozenset[str]] = {}

    def allow(self, narrative_grammar_id: str, *presenter_grammar_ids: str) -> None:
        if not narrative_grammar_id:
            raise ValueError("COMPATIBILITY_WITHOUT_NARRATIVE_ID:narrative id required")
        for presenter_id in presenter_grammar_ids:
            if not presenter_id:
                raise ValueError(
                    "COMPATIBILITY_WITHOUT_PRESENTER_ID:presenter id required"
                )
        existing = self._table.get(narrative_grammar_id, frozenset())
        self._table[narrative_grammar_id] = existing | frozenset(presenter_grammar_ids)

    def allowed(self, narrative_grammar_id: str) -> frozenset[str] | None:
        """Permitted presenter ids, or ``None`` when unrestricted."""
        return self._table.get(narrative_grammar_id)

    def is_compatible(self, narrative_grammar_id: str, presenter_grammar_id: str) -> bool:
        permitted = self.allowed(narrative_grammar_id)
        if permitted is None:
            return True
        return presenter_grammar_id in permitted

    def list_narratives(self) -> list[str]:
        return sorted(self._table)

    def validate_all(self) -> tuple[bool, list[str]]:
        """Every referenced presenter grammar must actually be registered."""
        errors = [
            f"UNKNOWN_PRESENTER_IN_COMPATIBILITY:{narrative_id}->{presenter_id}"
            for narrative_id, presenters in sorted(self._table.items())
            for presenter_id in sorted(presenters)
            if not PRESENTER_GRAMMAR_REGISTRY.has(presenter_id)
        ]
        return (not errors), errors

    def to_dict(self) -> dict[str, list[str]]:
        return {
            narrative_id: sorted(presenters)
            for narrative_id, presenters in sorted(self._table.items())
        }


#: The single grammar-compatibility authority.
GRAMMAR_COMPATIBILITY_REGISTRY = GrammarCompatibilityRegistry()

# A documentary arc is performed by a narrator or a reconstruction, not by a
# presenter selling something. The table states that; nothing branches on it.
GRAMMAR_COMPATIBILITY_REGISTRY.allow(
    "documentary", "documentary_explainer", "historical_reconstruction"
)
# An explanatory arc is performed directly, or taught.
GRAMMAR_COMPATIBILITY_REGISTRY.allow(
    "explanatory", "avatar_explainer", "educational_lecture", "product_presentation"
)
# A story arc is performed by a character or narrated.
GRAMMAR_COMPATIBILITY_REGISTRY.allow(
    "story", "historical_reconstruction", "documentary_explainer"
)
# Short form is performed directly.
GRAMMAR_COMPATIBILITY_REGISTRY.allow(
    "short_form", "avatar_explainer", "educational_lecture", "product_presentation"
)


__all__ = [
    "AVATAR_EXPLAINER",
    "BUILTIN_PRESENTER_GRAMMARS",
    "DOCUMENTARY_EXPLAINER",
    "EDUCATIONAL_LECTURE",
    "GRAMMAR_COMPATIBILITY_REGISTRY",
    "HISTORICAL_RECONSTRUCTION",
    "PRESENTER_GRAMMAR_REGISTRY",
    "PRODUCT_PRESENTATION",
    "GrammarCompatibilityRegistry",
    "PresenterGrammarRegistry",
    "register_builtin_presenter_grammars",
]
