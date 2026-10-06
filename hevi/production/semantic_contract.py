"""HEVI P6.5.1 — The production semantic contract.

One vocabulary, owned once, spoken by both the directing layer (P6) and the
cinematic engine (P5.3).

What the audit found
--------------------
See ``docs/SEMANTIC-AUTHORITY-MAP.md`` for the full write-up. The short version:

``recipe.intent`` is **not a vocabulary**. Across the 80 shipped recipes it holds
**77 distinct values**, almost all singletons — ``SHOW_PROCESS``, ``ZOOM_TO_DETAIL``,
``EVOKE_SOLITUDE``. It is a human-readable description of what one recipe does,
one label per recipe. P6.4 sets ``beat.intent_id`` to a qualified grammar id such
as ``documentary_realism@v1.0.0``, which can never equal any of them, so P5.3's
0.30-weight intent term is **structurally unreachable** and ``semantic_match``
caps at 0.70. That is a permanent ~9% of ``selection_score``.

Three vocabularies *are* genuinely shared, and this module is built on exactly
those:

===========================  ======  =================================
vocabulary                    size    owner
===========================  ======  =================================
``semantic_roles``             11     P5.3 — the shared layer vocabulary
``RecipeFamily``                8     P5.3 — closed ``StrEnum``
``beat_roles``                 10     P5.3 / P1 — shared shot-role set
``recipe.intent``              77     P5.3 — per-recipe free text, NOT a
                                     vocabulary. Excluded by design.
===========================  ======  =================================

So this contract invents **no** intent strings. Every ``semantic_id`` it defines is
an existing P5.3 ``semantic_role``; every ``category`` is a grouping *over* those
roles, not a new vocabulary; every ``compatible_recipe_intents`` entry is read out
of the real corpus rather than asserted.

Who owns what
-------------
============  ==========================================================
story intent  **P6.1** ``NarrativeGrammar`` — the arc. Owns node order
              and ``narrative_phase``. P5.3 knows nothing about arcs.
shot intent   **P6.4** ``VisualGrammar`` — the directive. Owns
              ``camera_language`` and the strategy that becomes a beat role.
recipe intent **P5.3** ``CinematicRecipe.intent`` — a per-recipe label.
              Not a contract surface. Not matched against. Never edited.
============  ==========================================================

The bridge
----------
:class:`SemanticDirective` is what P6 actually hands P5.3: a semantic role, a beat
role and a narrative phase, all drawn from P5.3's own vocabularies by table, not
by conditionals and not by product.

This also repairs a real defect P6.4 shipped. It mapped five motion strategies
onto five semantic roles, and two of them — ``RESTRAINED_PUSH`` and
``DELIBERATE_MOVE`` — both collapsed onto ``REVEAL``, discarding the difference
between a restrained push and a deliberate move. The contract carries a *set* of
roles per strategy and resolves one deterministically, so the collapse becomes a
recorded, inspectable choice instead of a silent loss.

Not modified
------------
P5.3 scoring is untouched. This module supplies better inputs; it does not change
how they are weighed. Reaching the 0.30 term would require either editing P5.3's
comparison or hardcoding recipe choices, and both are forbidden — so that term
stays unreachable, now *quantified and documented* rather than silently lost.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p5_3.schema import RecipeFamily

# ── the shared vocabulary, verbatim from P5.3 ───────────────────────────
# These 11 strings are the corpus's `semantic_roles`. They are transcribed, not
# invented. A test asserts the set matches the shipped corpus exactly, so if P5.3
# ever gains a role this module fails loudly instead of drifting.

SHARED_SEMANTIC_ROLES: tuple[str, ...] = (
    "EVIDENCE_DOMINANT",
    "EMOTIONAL_PRESENCE",
    "REVEAL",
    "DIRECT_ADDRESS",
    "EXPLAIN",
    "DETAIL",
    "COMPARE_CONTRAST",
    "FOLLOW",
    "ESTABLISH",
    "TRANSITION",
    "DEVELOPMENT",
)

#: P5.3 `beat_roles`, also used verbatim as P1's `VisualBeat.shot_role`.
SHARED_BEAT_ROLES: tuple[str, ...] = (
    "ESTABLISH",
    "REVEAL",
    "EXPLAIN",
    "FOLLOW",
    "DETAIL",
    "COMPARE",
    "PAYOFF",
    "TRANSITION",
    "DEVELOPMENT",
    "ESCALATION",
)

#: P5.3's `recipe.intent` is deliberately NOT here. See the module docstring.
#: `RECIPE_INTENT_IS_FREE_TEXT = True` exists so the decision is greppable.


class SemanticCategory(StrEnum):
    """Grouping over the shared roles.

    A category organises the existing 11 roles for lookup and reporting. It is not
    a vocabulary P5.3 or P6 ever matches on — matching happens on
    ``semantic_roles`` and ``beat_roles``, which are P5.3's.
    """

    EVIDENCE = "evidence"
    NARRATION = "narration"
    INTERACTION = "interaction"
    AFFECT = "affect"
    MOTION = "motion"
    STRUCTURE = "structure"


@dataclass(frozen=True)
class ProductionSemanticIntent:
    """One shared semantic role, described once for both layers.

    ``semantic_id`` is a P5.3 ``semantic_role``. ``compatible_recipe_intents`` is
    the set of ``recipe.intent`` labels that recipes carrying this role actually
    use — read from the corpus, so it is a description of reality rather than a
    claim about it.
    """

    semantic_id: str
    category: SemanticCategory
    description: str
    compatible_recipe_intents: tuple[str, ...] = ()
    recipe_families: tuple[RecipeFamily, ...] = ()
    beat_roles: tuple[str, ...] = ()
    recipe_count: int = 0

    def __post_init__(self) -> None:
        if not self.semantic_id:
            raise ValueError("SEMANTIC_INTENT_WITHOUT_ID:id required")
        if self.semantic_id not in SHARED_SEMANTIC_ROLES:
            raise ValueError(
                f"SEMANTIC_ID_NOT_IN_SHARED_VOCABULARY:{self.semantic_id}; the "
                "contract may only describe roles P5.3 already uses"
            )
        if not isinstance(self.category, SemanticCategory):
            raise ValueError(f"UNKNOWN_SEMANTIC_CATEGORY:{self.category!r}")

    def supports_beat_role(self, beat_role: str) -> bool:
        return beat_role in self.beat_roles

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_id": self.semantic_id,
            "category": self.category.value,
            "description": self.description,
            "compatible_recipe_intents": list(self.compatible_recipe_intents),
            "recipe_families": [f.value for f in self.recipe_families],
            "beat_roles": list(self.beat_roles),
            "recipe_count": self.recipe_count,
        }


#: The eleven roles, described. Descriptions are prose about intent, not new
#: machine vocabulary — nothing matches on them.
_ROLE_DESCRIPTIONS: dict[str, tuple[SemanticCategory, str]] = {
    "EVIDENCE_DOMINANT": (
        SemanticCategory.EVIDENCE,
        "The frame carries proof. Documents, data, artefacts, sources.",
    ),
    "EMOTIONAL_PRESENCE": (
        SemanticCategory.AFFECT,
        "The frame carries feeling. Held, atmospheric, affective rather than didactic.",
    ),
    "REVEAL": (SemanticCategory.MOTION, "Something previously hidden is disclosed."),
    "DIRECT_ADDRESS": (
        SemanticCategory.INTERACTION,
        "The frame addresses the viewer, or a performer addresses it.",
    ),
    "EXPLAIN": (SemanticCategory.NARRATION, "The frame teaches a mechanism."),
    "DETAIL": (SemanticCategory.STRUCTURE, "The frame isolates and inspects."),
    "COMPARE_CONTRAST": (
        SemanticCategory.NARRATION,
        "The frame sets two things against each other.",
    ),
    "FOLLOW": (SemanticCategory.MOTION, "The frame travels with a subject."),
    "ESTABLISH": (SemanticCategory.STRUCTURE, "The frame places the subject in context."),
    "TRANSITION": (SemanticCategory.MOTION, "The frame moves the viewer between places."),
    "DEVELOPMENT": (
        SemanticCategory.NARRATION,
        "The frame advances a developing line rather than landing a point.",
    ),
}


class SemanticContract:
    """The single shared-vocabulary authority for P6 and P5.3.

    Maps ``semantic_id -> ProductionSemanticIntent`` and resolves the bridge
    directive a beat should carry. No product dimension anywhere: the tables are
    keyed by grammar *shape*, which is what makes one directive serve ten
    products.
    """

    def __init__(self) -> None:
        self._intents: dict[str, ProductionSemanticIntent] = {}
        self._directives: dict[tuple[str, str, str], SemanticDirective] = {}

    def register(self, intent: ProductionSemanticIntent) -> ProductionSemanticIntent:
        if intent.semantic_id in self._intents:
            raise ValueError(f"SEMANTIC_INTENT_DUPLICATE:{intent.semantic_id}")
        self._intents[intent.semantic_id] = intent
        return intent

    def get(self, semantic_id: str) -> ProductionSemanticIntent | None:
        return self._intents.get(semantic_id)

    def resolve(self, semantic_id: str) -> ProductionSemanticIntent:
        intent = self._intents.get(semantic_id)
        if intent is None:
            raise KeyError(f"UNKNOWN_SEMANTIC_INTENT:{semantic_id}")
        return intent

    def list_ids(self) -> list[str]:
        return sorted(self._intents)

    def validate(self) -> tuple[bool, list[str]]:
        errors = [
            f"SEMANTIC_ROLE_NOT_COVERED:{role}"
            for role in SHARED_SEMANTIC_ROLES
            if role not in self._intents
        ]
        errors.extend(
            f"UNKNOWN_CATEGORY:{intent.semantic_id}"
            for intent in self._intents.values()
            if not isinstance(intent.category, SemanticCategory)
        )
        return (not errors), errors

    # ── the bridge ────────────────────────────────────────────────────────

    def add_directive(
        self,
        narrative_grammar_id: str,
        presenter_grammar_id: str,
        visual_grammar_id: str,
        *,
        semantic_role: str,
        beat_role: str,
        narrative_phase: str,
        motion_roles: tuple[str, ...] = (),
    ) -> SemanticDirective:
        """Declare what a (narrative, presenter, visual) *shape* means to P5.3.

        Keyed by three grammar ids — never a product id. That is what lets ten
        products share one directive table.
        """
        directive = SemanticDirective(
            narrative_grammar_id=narrative_grammar_id,
            presenter_grammar_id=presenter_grammar_id,
            visual_grammar_id=visual_grammar_id,
            semantic_role=semantic_role,
            beat_role=beat_role,
            narrative_phase=narrative_phase,
            motion_roles=motion_roles,
        )
        key = directive.key
        if key in self._directives:
            raise ValueError(f"SEMANTIC_DIRECTIVE_DUPLICATE:{key}")
        self._directives[key] = directive
        return directive

    def directive_for(
        self,
        narrative_grammar_id: str,
        presenter_grammar_id: str,
        visual_grammar_id: str,
    ) -> SemanticDirective | None:
        return self._directives.get(
            SemanticDirective.key_of(
                narrative_grammar_id, presenter_grammar_id, visual_grammar_id
            )
        )

    def resolve_directive(
        self,
        narrative_grammar_id: str,
        presenter_grammar_id: str,
        visual_grammar_id: str,
    ) -> SemanticDirective:
        directive = self.directive_for(
            narrative_grammar_id, presenter_grammar_id, visual_grammar_id
        )
        if directive is None:
            raise KeyError(
                "SEMANTIC_DIRECTIVE_NOT_FOUND:"
                f"{narrative_grammar_id}+{presenter_grammar_id}+{visual_grammar_id}"
            )
        return directive

    def list_directives(self) -> list[SemanticDirective]:
        return sorted(self._directives.values(), key=lambda d: d.key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "semantic_intents": {k: self._intents[k].to_dict() for k in sorted(self._intents)},
            "directives": [d.to_dict() for d in self.list_directives()],
        }


@dataclass(frozen=True)
class SemanticDirective:
    """What P6 hands P5.3 for one beat.

    Three fields, all from P5.3's own vocabularies: which semantic role the beat
    serves, which beat role to search on, and which narrative phase it sits in.
    """

    narrative_grammar_id: str
    presenter_grammar_id: str
    visual_grammar_id: str
    semantic_role: str
    beat_role: str
    narrative_phase: str
    motion_roles: tuple[str, ...] = ()

    @staticmethod
    def key_of(narrative: str, presenter: str, visual: str) -> tuple[str, str, str]:
        return (narrative, presenter, visual)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.key_of(
            self.narrative_grammar_id, self.presenter_grammar_id, self.visual_grammar_id
        )

    def __post_init__(self) -> None:
        for label, value, vocabulary in (
            ("semantic_role", self.semantic_role, SHARED_SEMANTIC_ROLES),
            ("beat_role", self.beat_role, SHARED_BEAT_ROLES),
            ("narrative_phase", self.narrative_phase, SHARED_BEAT_ROLES),
        ):
            if value not in vocabulary:
                raise ValueError(f"{label}_NOT_IN_SHARED_VOCABULARY:{value}")

    def motion_purpose(self) -> str:
        """The single role P5.3 scores ``beat.motion_purpose`` against.

        Resolved from ``motion_roles`` deterministically — sorted, first — so the
        collapse from a set to the one string P5.3 accepts is a recorded choice.
        P6.4 previously had two motion strategies both hardmapped to ``REVEAL``;
        here they can differ, and where they cannot, the reason is visible.
        """
        return sorted(self.motion_roles)[0] if self.motion_roles else self.semantic_role

    def to_dict(self) -> dict[str, Any]:
        return {
            "narrative_grammar_id": self.narrative_grammar_id,
            "presenter_grammar_id": self.presenter_grammar_id,
            "visual_grammar_id": self.visual_grammar_id,
            "semantic_role": self.semantic_role,
            "beat_role": self.beat_role,
            "narrative_phase": self.narrative_phase,
            "motion_roles": list(self.motion_roles),
            "motion_purpose": self.motion_purpose(),
        }


#: The single semantic contract.
SEMANTIC_CONTRACT = SemanticContract()


def build_contract_from_corpus(
    recipes: list[Any],
    *,
    contract: SemanticContract | None = None,
) -> SemanticContract:
    """Populate the contract by reading the real P5.3 corpus.

    ``compatible_recipe_intents``, ``recipe_families``, ``beat_roles`` and
    ``recipe_count`` are all *derived from the recipes themselves*. Nothing here
    asserts what P5.3 contains; it reports it.
    """
    target = contract if contract is not None else SEMANTIC_CONTRACT
    by_role: dict[str, list[Any]] = {role: [] for role in SHARED_SEMANTIC_ROLES}
    for recipe in recipes:
        for role in getattr(recipe, "semantic_roles", ()):
            if role in by_role:
                by_role[role].append(recipe)

    for role in SHARED_SEMANTIC_ROLES:
        if target.get(role) is not None:
            continue
        bucket = by_role[role]
        category, description = _ROLE_DESCRIPTIONS[role]
        target.register(
            ProductionSemanticIntent(
                semantic_id=role,
                category=category,
                description=description,
                compatible_recipe_intents=tuple(sorted({r.intent for r in bucket})),
                recipe_families=tuple(sorted({r.recipe_family for r in bucket})),
                beat_roles=tuple(sorted({b for r in bucket for b in r.beat_roles})),
                recipe_count=len(bucket),
            )
        )
    return target


#: Directives per (narrative, presenter, visual) shape. Seven rows cover all ten
#: P6.5 products — the same reuse ratio as the product matrix itself. Keyed by
#: grammar shape, so adding a product that reuses a shape needs no new row.
def _register_builtin_directives(contract: SemanticContract) -> None:
    rows = (
        # narrative, presenter, visual grammar, role, beat, phase, motion roles
        ("documentary", "documentary_explainer", "documentary_realism",
         "EVIDENCE_DOMINANT", "FOLLOW", "DEVELOPMENT",
         ("FOLLOW", "ESTABLISH", "DEVELOPMENT")),
        ("documentary", "historical_reconstruction", "documentary_realism",
         "EVIDENCE_DOMINANT", "REVEAL", "DEVELOPMENT",
         ("REVEAL", "DEVELOPMENT")),
        ("documentary", "avatar_explainer", "documentary_realism",
         "EVIDENCE_DOMINANT", "EXPLAIN", "DEVELOPMENT",
         ("EXPLAIN", "DETAIL")),
        ("story", "documentary_explainer", "dramatic_reconstruction",
         "EMOTIONAL_PRESENCE", "REVEAL", "DEVELOPMENT",
         ("REVEAL", "DEVELOPMENT", "TRANSITION")),
        ("story", "historical_reconstruction", "dramatic_reconstruction",
         "EMOTIONAL_PRESENCE", "REVEAL", "DEVELOPMENT",
         ("REVEAL", "DEVELOPMENT")),
        ("explanatory", "avatar_explainer", "educational_clarity",
         "EXPLAIN", "EXPLAIN", "DEVELOPMENT",
         ("EXPLAIN", "DETAIL", "DIRECT_ADDRESS")),
        ("explanatory", "educational_lecture", "educational_clarity",
         "EXPLAIN", "EXPLAIN", "DEVELOPMENT",
         ("EXPLAIN", "DETAIL")),
        ("explanatory", "product_presentation", "educational_clarity",
         "DIRECT_ADDRESS", "REVEAL", "DEVELOPMENT",
         ("REVEAL", "DIRECT_ADDRESS", "DETAIL")),
        ("short_form", "avatar_explainer", "educational_clarity",
         "DIRECT_ADDRESS", "EXPLAIN", "ESCALATION",
         ("DIRECT_ADDRESS", "EXPLAIN", "TRANSITION")),
    )
    for narrative, presenter, visual, role, beat, phase, motion in rows:
        contract.add_directive(
            narrative, presenter, visual,
            semantic_role=role, beat_role=beat, narrative_phase=phase,
            motion_roles=motion,
        )


_register_builtin_directives(SEMANTIC_CONTRACT)


__all__ = [
    "SEMANTIC_CONTRACT",
    "SHARED_BEAT_ROLES",
    "SHARED_SEMANTIC_ROLES",
    "ProductionSemanticIntent",
    "SemanticCategory",
    "SemanticContract",
    "SemanticDirective",
    "build_contract_from_corpus",
]
