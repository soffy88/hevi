"""HEVI P6.5 — The ten commercial product profiles, as data.

This module contains **no logic**. Ten products are ten rows, not ten branches.
The single compiler in ``product_compiler.py`` reads whatever these rows declare;
it has never heard of any of them by name.

    "历史现场解说"  →  P02_HISTORY_RECONSTRUCTION  →  a row
                    →  ProductProfile              →  ProductCompiler

Not:

    if is_history:
        use_historical_narrative()

The naming collision, stated plainly
-----------------------------------
P6.0 already owns a closed ``ProductType`` enum with ``P01_…``–``P10_…`` values,
and **nine of its ten slots mean something different** from the commercial labels
in the P6.5 brief:

    slot   P6.0 ProductType              P6.5 commercial label
    P02    P02_NARRATED_KNOWLEDGE       P02_HISTORY_RECONSTRUCTION
    P03    P03_HISTORICAL_REENACTMENT   P03_DOCUMENTARY
    P04    P04_CHARACTER_DOCUMENTARY    P04_SCIENCE_EXPLAINER
    P05    P05_DOCUMENTARY              P05_NEWS_ANALYSIS
    P06    P06_NARRATIVE_FILM           P06_EDUCATIONAL
    P07    P07_CINEMATIC_KNOWLEDGE      P07_MARKETING
    P08    P08_COMMERCIAL               P08_BRAND_STORY
    P09    P09_TUTORIAL                 P09_SHORT_VIDEO
    P10    P10_SHORT_FORM               P10_CINEMATIC_STORY

Only ``P01_AVATAR_EXPLAINER`` agrees. Treating the two namespaces as one enum
would make ``P03_DOCUMENTARY`` and ``P03_HISTORICAL_REENACTMENT`` look like
variants of the same thing. They are not.

So they are kept **separate on purpose**:

* ``ProductType`` (P6.0, frozen) — the canonical production taxonomy, and the
  required ``ProductProfile.product_type`` field.
* ``CommercialProduct`` (here) — the commercial catalogue a customer-facing
  brief is written in.

Every profile carries **both**, and the pairing is explicit data, so no code path
infers one from the other. The two are deliberately not interchangeable: in
exactly 9 of 10 slots the strings differ, so ``CommercialProduct("P03_DOCUMENTARY")``
succeeds where ``ProductType("P03_DOCUMENTARY")`` raises. That asymmetry is the
safety property — a mix-up fails loudly instead of silently compiling the wrong
product. ``tests/test_p6_5_product_compiler.py`` pins it in both directions.

Four grammar shapes, ten products
---------------------------------
The ten profiles resolve to only **four** distinct grammar combinations:

    A  documentary / documentary_explainer / documentary_realism / documentary_realism
    B  story / documentary_explainer / cinematic_drama / dramatic_reconstruction
    C  story / historical_reconstruction / cinematic_drama / dramatic_reconstruction
    D  explanatory / {avatar_explainer, educational_lecture, product_presentation}
       / educational_clarity / educational_clarity

Six products share a shape and differ by purpose, audience, duration and aspect.
That is the thesis of P6.5 made measurable: one product is not one pipeline.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from hevi.production.p6.schema import (
    AspectPolicy,
    DurationPolicy,
    GrammarKind,
    GrammarRef,
    ProductProfile,
    ProductType,
)

#: Grammar refs every commercial profile carries. Narrative and presenter only —
#: P6.5 composes grammars, it does not invent new ones.
_COMPOSITION_REFS = (
    GrammarRef(kind=GrammarKind.NARRATIVE, required=True),
    GrammarRef(kind=GrammarKind.PRESENTER, required=True),
)


class CommercialProduct(StrEnum):
    """Customer-facing catalogue labels from the P6.5 brief.

    A separate namespace from :class:`~hevi.production.p6.schema.ProductType` on
    purpose — see the module docstring. Not a product taxonomy for branching: it
    is the set of rows the catalogue ships, nothing more.
    """

    P01_AVATAR_EXPLAINER = "P01_AVATAR_EXPLAINER"
    P02_HISTORY_RECONSTRUCTION = "P02_HISTORY_RECONSTRUCTION"
    P03_DOCUMENTARY = "P03_DOCUMENTARY"
    P04_SCIENCE_EXPLAINER = "P04_SCIENCE_EXPLAINER"
    P05_NEWS_ANALYSIS = "P05_NEWS_ANALYSIS"
    P06_EDUCATIONAL = "P06_EDUCATIONAL"
    P07_MARKETING = "P07_MARKETING"
    P08_BRAND_STORY = "P08_BRAND_STORY"
    P09_SHORT_VIDEO = "P09_SHORT_VIDEO"
    P10_CINEMATIC_STORY = "P10_CINEMATIC_STORY"


def _profile(
    commercial: CommercialProduct,
    product_type: ProductType,
    purpose: str,
    audience: str,
    *,
    narrative: str,
    presenter: str,
    style: str,
    grammar: str,
    target_s: float,
    min_s: float,
    max_s: float,
    aspect: AspectPolicy = AspectPolicy.LANDSCAPE_16_9,
) -> ProductProfile:
    return ProductProfile(
        id=commercial.value,
        product_type=product_type,
        purpose=purpose,
        audience=audience,
        grammars=_COMPOSITION_REFS,
        duration_policy=DurationPolicy(target_s=target_s, min_s=min_s, max_s=max_s),
        aspect_policy=aspect,
        narrative_grammar_id=narrative,
        presenter_grammar_id=presenter,
        visual_style_id=style,
        visual_grammar_id=grammar,
    )


# ── the ten rows ────────────────────────────────────────────────────────

P01_AVATAR_EXPLAINER = _profile(
    CommercialProduct.P01_AVATAR_EXPLAINER,
    ProductType.AVATAR_EXPLAINER,
    purpose="Explain a subject through a presented avatar",
    audience="general",
    narrative="explanatory",
    presenter="avatar_explainer",
    style="educational_clarity",
    grammar="educational_clarity",
    target_s=180.0,
    min_s=90.0,
    max_s=420.0,
)

P02_HISTORY_RECONSTRUCTION = _profile(
    CommercialProduct.P02_HISTORY_RECONSTRUCTION,
    ProductType.HISTORICAL_REENACTMENT,
    purpose="Reconstruct a historical scene on location and disclose the staging",
    audience="history viewers",
    narrative="story",
    presenter="historical_reconstruction",
    style="cinematic_drama",
    grammar="dramatic_reconstruction",
    target_s=480.0,
    min_s=240.0,
    max_s=900.0,
)

P03_DOCUMENTARY = _profile(
    CommercialProduct.P03_DOCUMENTARY,
    ProductType.DOCUMENTARY,
    purpose="Document a subject with observed footage",
    audience="general",
    narrative="documentary",
    presenter="documentary_explainer",
    style="documentary_realism",
    grammar="documentary_realism",
    target_s=900.0,
    min_s=480.0,
    max_s=1800.0,
)

P04_SCIENCE_EXPLAINER = _profile(
    CommercialProduct.P04_SCIENCE_EXPLAINER,
    ProductType.NARRATED_KNOWLEDGE,
    purpose="Explain a scientific mechanism clearly",
    audience="students",
    narrative="explanatory",
    presenter="avatar_explainer",
    style="educational_clarity",
    grammar="educational_clarity",
    target_s=240.0,
    min_s=120.0,
    max_s=600.0,
)

P05_NEWS_ANALYSIS = _profile(
    CommercialProduct.P05_NEWS_ANALYSIS,
    ProductType.CINEMATIC_KNOWLEDGE,
    purpose="Analyse a news event against available evidence",
    audience="informed viewers",
    narrative="documentary",
    presenter="documentary_explainer",
    style="documentary_realism",
    grammar="documentary_realism",
    target_s=300.0,
    min_s=150.0,
    max_s=600.0,
)

P06_EDUCATIONAL = _profile(
    CommercialProduct.P06_EDUCATIONAL,
    ProductType.TUTORIAL,
    purpose="Teach a procedure step by step",
    audience="learners",
    narrative="explanatory",
    presenter="educational_lecture",
    style="educational_clarity",
    grammar="educational_clarity",
    target_s=420.0,
    min_s=180.0,
    max_s=900.0,
)

P07_MARKETING = _profile(
    CommercialProduct.P07_MARKETING,
    ProductType.COMMERCIAL,
    purpose="Present a product against substantiated claims",
    audience="prospects",
    narrative="explanatory",
    presenter="product_presentation",
    style="educational_clarity",
    grammar="educational_clarity",
    target_s=45.0,
    min_s=15.0,
    max_s=120.0,
)

P08_BRAND_STORY = _profile(
    CommercialProduct.P08_BRAND_STORY,
    ProductType.NARRATIVE_FILM,
    purpose="Tell a brand story through a narrative arc",
    audience="customers",
    narrative="story",
    presenter="documentary_explainer",
    style="cinematic_drama",
    grammar="dramatic_reconstruction",
    target_s=600.0,
    min_s=300.0,
    max_s=1200.0,
)

P09_SHORT_VIDEO = _profile(
    CommercialProduct.P09_SHORT_VIDEO,
    ProductType.SHORT_FORM,
    purpose="Deliver one idea in a short vertical video",
    audience="feed scrollers",
    narrative="short_form",
    presenter="avatar_explainer",
    style="educational_clarity",
    grammar="educational_clarity",
    target_s=30.0,
    min_s=15.0,
    max_s=90.0,
    aspect=AspectPolicy.VERTICAL_9_16,
)

P10_CINEMATIC_STORY = _profile(
    CommercialProduct.P10_CINEMATIC_STORY,
    ProductType.NARRATIVE_FILM,
    purpose="Tell a cinematic story",
    audience="general",
    narrative="story",
    presenter="historical_reconstruction",
    style="cinematic_drama",
    grammar="dramatic_reconstruction",
    target_s=720.0,
    min_s=360.0,
    max_s=1440.0,
    aspect=AspectPolicy.CINEMATIC_2_39,
)

BUILTIN_PRODUCT_PROFILES: tuple[ProductProfile, ...] = (
    P01_AVATAR_EXPLAINER,
    P02_HISTORY_RECONSTRUCTION,
    P03_DOCUMENTARY,
    P04_SCIENCE_EXPLAINER,
    P05_NEWS_ANALYSIS,
    P06_EDUCATIONAL,
    P07_MARKETING,
    P08_BRAND_STORY,
    P09_SHORT_VIDEO,
    P10_CINEMATIC_STORY,
)


class CommercialProductRegistry:
    """The authority for the commercial catalogue.

    Its entire responsibility is ``id -> ProductProfile``. It holds no compiler,
    no dispatch table, and no per-product behaviour: looking a profile up returns
    the same row whoever asked, and the compiler that consumes it has no way to
    ask "which product is this?" to get a different answer.

    Not a duplicate of P6.0's ``PRODUCT_PROFILE_REGISTRY``
    ---------------------------------------------------
    P6.0 already owns ``ProductProfileRegistry`` / ``PRODUCT_PROFILE_REGISTRY``
    and it is a strict superset of what the P6.5 brief asks for here
    (``id@version -> ProductProfile``). Creating a second registry under the same
    name would be a duplicate authority. The two hold genuinely different
    subjects, so this is a sibling rather than a copy — the same way P6.1 and
    P6.2 added ``NARRATIVE_GRAMMAR_REGISTRY`` and
    ``PRESENTER_GRAMMAR_REGISTRY`` beside P6.0's ``GRAMMAR_REGISTRY``:

    ==========================  ==========================================
    P6.0 canonical registry     P6.5 commercial catalogue (here)
    ==========================  ==========================================
    key: ``id@version``         key: ``id``
    profiles carry *embedded*   profiles carry grammar *references*
    grammars (P6.0's own model)  resolved by P6.1-P6.4 at compile time
    governs the canonical       governs the ten customer-facing rows
    production taxonomy
    ==========================  ==========================================

    ``assert_no_id_collision()`` keeps the two namespaces from ever drifting
    into the same id.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ProductProfile] = {}

    def register(self, profile: ProductProfile) -> ProductProfile:
        if not isinstance(profile, ProductProfile):
            raise ValueError(f"NOT_A_PRODUCT_PROFILE:{type(profile).__name__}")
        if profile.id in self._profiles:
            raise ValueError(f"PRODUCT_PROFILE_DUPLICATE:{profile.id} already registered")
        self._profiles[profile.id] = profile
        return profile

    def get(self, profile_id: str) -> ProductProfile | None:
        if not profile_id:
            return None
        return self._profiles.get(profile_id)

    def resolve(self, profile_id: str) -> ProductProfile:
        profile = self.get(profile_id)
        if profile is None:
            raise KeyError(f"UNKNOWN_PRODUCT_PROFILE:{profile_id}")
        return profile

    def has(self, profile_id: str) -> bool:
        return self.get(profile_id) is not None

    def list_ids(self) -> list[str]:
        return sorted(self._profiles)

    def list_all(self) -> list[ProductProfile]:
        return [self._profiles[k] for k in self.list_ids()]

    def commercial_products(self) -> list[CommercialProduct]:
        return [CommercialProduct(k) for k in self.list_ids()]

    def validate(self, profile_id: str) -> tuple[bool, list[str]]:
        profile = self.get(profile_id)
        if profile is None:
            return False, [f"UNKNOWN_PRODUCT_PROFILE:{profile_id}"]
        errors: list[str] = []
        required = (
            profile.narrative_grammar_id,
            profile.presenter_grammar_id,
            profile.visual_style_id,
            profile.visual_grammar_id,
        )
        missing = [
            name
            for name, value in zip(
                (
                    "narrative_grammar_id",
                    "presenter_grammar_id",
                    "visual_style_id",
                    "visual_grammar_id",
                ),
                required,
                strict=True,
            )
            if not value
        ]
        if missing:
            errors.append(f"INVALID_PRODUCT_PROFILE:{'|'.join(missing)}")
        if not profile.grammars:
            errors.append("INVALID_PRODUCT_PROFILE:grammars")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for profile_id in self.list_ids():
            ok, profile_errors = self.validate(profile_id)
            if not ok:
                errors.extend(f"{profile_id}:{e}" for e in profile_errors)
        return (not errors), errors

    def assert_no_id_collision(self) -> None:
        """Refuse to share an id with P6.0's canonical registry.

        Same guard, different reason to the ``CommercialProduct`` / ``ProductType``
        split: two registries answering for one id is a duplicate authority in
        waiting, and it is much cheaper to notice here than in production.
        """
        from hevi.production.p6.registry import PRODUCT_PROFILE_REGISTRY as canonical

        collisions = sorted(set(self.list_ids()) & set(canonical.list_ids()))
        if collisions:
            raise ValueError(
                f"PRODUCT_PROFILE_ID_COLLISION:{','.join(collisions)} exists in both "
                "the canonical P6.0 registry and the commercial catalogue"
            )

    def stats(self) -> dict[str, Any]:
        shapes = {
            (
                p.narrative_grammar_id,
                p.presenter_grammar_id,
                p.visual_style_id,
                p.visual_grammar_id,
            )
            for p in self._profiles.values()
        }
        return {
            "profiles": len(self._profiles),
            "distinct_grammar_shapes": len(shapes),
            "product_types_used": len({p.product_type for p in self._profiles.values()}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {k: self._profiles[k].to_dict() for k in self.list_ids()}


#: The single product profile authority.
COMMERCIAL_PRODUCT_REGISTRY = CommercialProductRegistry()


def register_builtin_product_profiles(*, force: bool = False) -> list[str]:
    """Register the ten built-in rows. Idempotent, never overwrites silently."""
    registered: list[str] = []
    for profile in BUILTIN_PRODUCT_PROFILES:
        if COMMERCIAL_PRODUCT_REGISTRY.has(profile.id) and not force:
            registered.append(profile.id)
            continue
        COMMERCIAL_PRODUCT_REGISTRY.register(profile)
        registered.append(profile.id)
    return registered


register_builtin_product_profiles()


__all__ = [
    "BUILTIN_PRODUCT_PROFILES",
    "COMMERCIAL_PRODUCT_REGISTRY",
    "P01_AVATAR_EXPLAINER",
    "P02_HISTORY_RECONSTRUCTION",
    "P03_DOCUMENTARY",
    "P04_SCIENCE_EXPLAINER",
    "P05_NEWS_ANALYSIS",
    "P06_EDUCATIONAL",
    "P07_MARKETING",
    "P08_BRAND_STORY",
    "P09_SHORT_VIDEO",
    "P10_CINEMATIC_STORY",
    "CommercialProduct",
    "CommercialProductRegistry",
    "register_builtin_product_profiles",
]
