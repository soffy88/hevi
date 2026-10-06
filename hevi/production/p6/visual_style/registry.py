"""HEVI P6.3 — Visual style registry, built-ins and style compatibility.

Three authorities, each answering one question:

``VISUAL_STYLE_REGISTRY``
    "What does documentary realism look like?" — holds
    :class:`~hevi.production.p6.visual_style.model.VisualStyleGrammar`.

``STYLE_COMPATIBILITY_REGISTRY``
    "Which styles may serve a given narrative?" — declarative data, keyed by
    narrative grammar id.

``BUILTIN_VISUAL_STYLES``
    The shipped general styles. None is product-named: ``documentary_realism``,
    ``archival_history``, ``educational_clarity``, ``cinematic_drama``,
    ``future_tech``, ``corporate_clean``.

Why compatibility is data
-------------------------
The alternative — ``if narrative == "documentary" and style ==
"cinematic_drama"`` — is the per-product branching the architecture forbids. A
table keyed by grammar id makes the rule data, so adding a pairing is a data
change and the branching guard stays green.

Not a rendering authority
-------------------------
Nothing here selects a renderer, generates an asset, calls an image model,
touches a provider, a timeline or a shot. Those prefixes are unimported here and
guarded by ``test_no_forbidden_import``.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p6.schema import ProductConstraint
from hevi.production.p6.visual_style.model import (
    ColorLanguage,
    CompositionLanguage,
    LightingLanguage,
    Mood,
    MotionLanguage,
    StyleCategory,
    TextureLanguage,
    VisualStyleGrammar,
)

_C = ProductConstraint

# ── Built-in visual styles ──────────────────────────────────────────────

DOCUMENTARY_REALISM = VisualStyleGrammar(
    id="documentary_realism",
    version="1.0.0",
    name="Documentary Realism",
    category=StyleCategory.DOCUMENTARY,
    description=(
        "Available light, observed framing, natural colour. The look of a camera "
        "that was present rather than arranged."
    ),
    mood=Mood.AUTHORITATIVE,
    color_language=ColorLanguage.NATURAL,
    composition_language=CompositionLanguage.DOCUMENTARY,
    texture_language=TextureLanguage.REALISTIC,
    motion_language=MotionLanguage.RESTRAINED,
    lighting_language=LightingLanguage.NATURAL,
    constraints=(
        _C(key="style_legibility", value="natural", rationale="natural light is the point"),
        _C(key="motion_restrained", value="true", rationale="an observed camera does not perform"),
    ),
)

ARCHIVAL_HISTORY = VisualStyleGrammar(
    id="archival_history",
    version="1.0.0",
    name="Archival History",
    category=StyleCategory.ARCHIVAL,
    description=(
        "Period colour, archival surface and available-light contrast. Reads as "
        "recovered record rather than contemporary reconstruction."
    ),
    mood=Mood.NOSTALGIC,
    color_language=ColorLanguage.WARM,
    composition_language=CompositionLanguage.OBSERVATIONAL,
    texture_language=TextureLanguage.ARCHIVAL,
    motion_language=MotionLanguage.DELIBERATE,
    lighting_language=LightingLanguage.DRAMATIC,
    constraints=(
        _C(key="archival_surface", value="required", rationale="the period has to be visible in the surface"),
        _C(key="style_legibility", value="period", rationale="period grade must stay readable"),
    ),
)

EDUCATIONAL_CLARITY = VisualStyleGrammar(
    id="educational_clarity",
    version="1.0.0",
    name="Educational Clarity",
    category=StyleCategory.EDITORIAL,
    description=(
        "Clean surface, even light, legible contrast. Nothing competes with what "
        "is being taught."
    ),
    mood=Mood.EDUCATIONAL,
    color_language=ColorLanguage.HIGH_CONTRAST,
    composition_language=CompositionLanguage.INFOGRAPHIC,
    texture_language=TextureLanguage.CLEAN,
    motion_language=MotionLanguage.RESTRAINED,
    lighting_language=LightingLanguage.STUDIO,
    constraints=(
        _C(key="legibility_first", value="true", rationale="clarity outranks mood in instruction"),
        _C(key="motion_restrained", value="true", rationale="movement distracts from the explanation"),
    ),
)

CINEMATIC_DRAMA = VisualStyleGrammar(
    id="cinematic_drama",
    version="1.0.0",
    name="Cinematic Drama",
    category=StyleCategory.CINEMATIC,
    description=(
        "Deliberate contrast and directional light. The frame is composed for "
        "effect rather than for availability."
    ),
    mood=Mood.DRAMATIC,
    color_language=ColorLanguage.CINEMATIC,
    composition_language=CompositionLanguage.CINEMATIC,
    texture_language=TextureLanguage.REALISTIC,
    motion_language=MotionLanguage.DELIBERATE,
    lighting_language=LightingLanguage.DRAMATIC,
    constraints=(
        _C(key="contrast_required", value="true", rationale="drama is carried by contrast"),
        _C(key="style_legibility", value="dramatic", rationale="shadow must not swallow the subject"),
    ),
)

FUTURE_TECH = VisualStyleGrammar(
    id="future_tech",
    version="1.0.0",
    name="Future Tech",
    category=StyleCategory.TECHNOLOGICAL,
    description=(
        "Cool cast, hard specular surfaces, fast legible motion. Reads as "
        "forward-looking rather than present-day."
    ),
    mood=Mood.FUTURISTIC,
    color_language=ColorLanguage.COOL,
    composition_language=CompositionLanguage.CINEMATIC,
    texture_language=TextureLanguage.FUTURISTIC,
    motion_language=MotionLanguage.FLUID,
    lighting_language=LightingLanguage.STUDIO,
    constraints=(
        _C(key="specular_surface", value="required", rationale="the surface is the signal"),
        _C(key="legibility_first", value="true", rationale="futuristic must not become illegible"),
    ),
)

CORPORATE_CLEAN = VisualStyleGrammar(
    id="corporate_clean",
    version="1.0.0",
    name="Corporate Clean",
    category=StyleCategory.BRAND_NEUTRAL,
    description=(
        "Even light, restrained motion, colour that stays out of the way. "
        "Deliberately unopinionated so brand assets carry the identity."
    ),
    mood=Mood.MINIMAL,
    color_language=ColorLanguage.NATURAL,
    composition_language=CompositionLanguage.PRESENTER_CENTERED,
    texture_language=TextureLanguage.CLEAN,
    motion_language=MotionLanguage.RESTRAINED,
    lighting_language=LightingLanguage.SOFT,
    constraints=(
        _C(key="brand_neutral", value="true", rationale="the brand supplies the identity, not the grade"),
        _C(key="motion_restrained", value="true", rationale="a neutral surface does not perform"),
    ),
)


BUILTIN_VISUAL_STYLES: tuple[VisualStyleGrammar, ...] = (
    DOCUMENTARY_REALISM,
    ARCHIVAL_HISTORY,
    EDUCATIONAL_CLARITY,
    CINEMATIC_DRAMA,
    FUTURE_TECH,
    CORPORATE_CLEAN,
)


# ── Visual style registry ───────────────────────────────────────────────


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


class VisualStyleRegistry:
    """Single authority for visual style definitions."""

    def __init__(self) -> None:
        self._styles: dict[str, VisualStyleGrammar] = {}
        self._versions: dict[str, list[str]] = {}

    @staticmethod
    def _key(style_id: str, version: str) -> str:
        return f"{style_id}@v{version}"

    def register(self, style: VisualStyleGrammar) -> VisualStyleGrammar:
        if not isinstance(style, VisualStyleGrammar):
            raise ValueError(f"NOT_A_VISUAL_STYLE:{type(style).__name__}")
        key = style.qualified_id
        if key in self._styles:
            raise ValueError(f"VISUAL_STYLE_IMMUTABLE:{key} already registered")
        self._styles[key] = style
        self._versions.setdefault(style.id, []).append(style.version)
        return style

    def get(self, ref: str, version: str | None = None) -> VisualStyleGrammar | None:
        """Look up by bare id or by ``id@version``; both spellings accepted."""
        style_id, embedded = _split_qualified(ref)
        target = version or embedded
        if target:
            direct = self._styles.get(self._key(style_id, target))
            if direct is not None:
                return direct
            stripped = target[1:] if target.startswith("v") else None
            if stripped:
                return self._styles.get(self._key(style_id, stripped))
            return None
        versions = self._versions.get(style_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=_version_sort_key)[-1]
        return self._styles.get(self._key(style_id, latest))

    def resolve(self, ref: str, version: str | None = None) -> VisualStyleGrammar:
        """Resolve or raise. A missing style is a defect, not a default."""
        style_id, embedded = _split_qualified(ref)
        style = self.get(style_id, version or embedded)
        if style is None:
            raise KeyError(f"UNKNOWN_VISUAL_STYLE:{ref}")
        return style

    def list_all(self) -> list[VisualStyleGrammar]:
        """Every registered style, across all ids and versions."""
        return list(self._styles.values())

    def list_ids(self) -> list[str]:
        return sorted(self._versions)

    def list_versions(self, style_id: str) -> list[str]:
        return list(self._versions.get(style_id, []))

    def has(self, ref: str, version: str | None = None) -> bool:
        return self.get(ref, version) is not None

    def list_by_category(self, category: StyleCategory) -> list[VisualStyleGrammar]:
        return [s for s in self._styles.values() if s.category is category]

    def validate(self, ref: str, version: str | None = None) -> tuple[bool, list[str]]:
        style = self.get(ref, version)
        if style is None:
            return False, [f"VISUAL_STYLE_NOT_FOUND:{ref}"]
        errors: list[str] = []
        if not isinstance(style.category, StyleCategory):
            errors.append("UNKNOWN_STYLE_CATEGORY")
        languages = style.languages()
        for channel, value in sorted(languages.items()):
            if not value:
                errors.append(f"EMPTY_STYLE_LANGUAGE:{channel}")
        if style.mood is None:
            errors.append("VISUAL_STYLE_WITHOUT_MOOD")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for style_id in self.list_ids():
            ok, style_errors = self.validate(style_id)
            if not ok:
                errors.extend(f"{style_id}:{e}" for e in style_errors)
        return (not errors), errors

    def stats(self) -> dict[str, Any]:
        by_category: dict[str, int] = {}
        for style in self._styles.values():
            by_category[style.category.value] = by_category.get(style.category.value, 0) + 1
        return {
            "total_styles": len(self._styles),
            "distinct_ids": len(self._versions),
            "by_category": dict(sorted(by_category.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        return {key: s.to_dict() for key, s in sorted(self._styles.items())}


#: The single visual style authority.
VISUAL_STYLE_REGISTRY = VisualStyleRegistry()


def register_builtin_styles(*, force: bool = False) -> list[str]:
    """Register the built-ins. Idempotent, and never overwrites silently."""
    registered: list[str] = []
    for style in BUILTIN_VISUAL_STYLES:
        existing = VISUAL_STYLE_REGISTRY.get(style.id, style.version)
        if existing is not None and not force:
            registered.append(style.qualified_id)
            continue
        if existing is not None and existing.content_hash() != style.content_hash():
            raise ValueError(
                f"VISUAL_STYLE_IMMUTABLE:{style.qualified_id} already registered "
                "with different content"
            )
        VISUAL_STYLE_REGISTRY.register(style)
        registered.append(style.qualified_id)
    return registered


register_builtin_styles()


# ── Style compatibility ─────────────────────────────────────────────────


class StyleCompatibilityRegistry:
    """Which visual styles may serve a given narrative grammar.

    The P6.1/P6.2 gap closed as data. Keyed by narrative grammar id, mapping to
    the set of permitted style ids. A narrative absent from the table permits
    every registered style, so a newly added narrative stays usable without a
    compatibility edit.
    """

    def __init__(self) -> None:
        self._table: dict[str, frozenset[str]] = {}

    def allow(self, narrative_grammar_id: str, *style_ids: str) -> None:
        if not narrative_grammar_id:
            raise ValueError("STYLE_COMPATIBILITY_WITHOUT_NARRATIVE_ID:id required")
        for style_id in style_ids:
            if not style_id:
                raise ValueError("STYLE_COMPATIBILITY_WITHOUT_STYLE_ID:style id required")
        existing = self._table.get(narrative_grammar_id, frozenset())
        self._table[narrative_grammar_id] = existing | frozenset(style_ids)

    def allowed(self, narrative_grammar_id: str) -> frozenset[str] | None:
        """Permitted style ids, or ``None`` when unrestricted."""
        return self._table.get(narrative_grammar_id)

    def is_compatible(self, narrative_grammar_id: str, style_id: str) -> bool:
        permitted = self.allowed(narrative_grammar_id)
        if permitted is None:
            return True
        return style_id in permitted

    def list_narratives(self) -> list[str]:
        return sorted(self._table)

    def validate_all(self) -> tuple[bool, list[str]]:
        """Every referenced style must actually be registered."""
        errors = [
            f"UNKNOWN_STYLE_IN_COMPATIBILITY:{narrative_id}->{style_id}"
            for narrative_id, styles in sorted(self._table.items())
            for style_id in sorted(styles)
            if not VISUAL_STYLE_REGISTRY.has(style_id)
        ]
        return (not errors), errors

    def to_dict(self) -> dict[str, list[str]]:
        return {
            narrative_id: sorted(styles)
            for narrative_id, styles in sorted(self._table.items())
        }


#: Composition languages able to carry each presenter performance.
#:
#: The second pairing dimension, and the reason ``PresenterIntent`` is an input
#: to the compiler at all. An avatar explainer or a lecture is a *performed*
#: shape and needs a frame built for a performer; framing it as observed
#: documentary or pure infographic contradicts the performance rather than
#: supporting it. Presenter shapes that are not performer-dependent (documentary,
#: historical, product) place no constraint and are absent from the table.
#:
#: Data, keyed by presenter grammar id — a general performance shape, never a
#: product. Adding a presenter means adding an entry, not a branch.
COMPOSITION_COMPATIBILITY: dict[str, frozenset[CompositionLanguage]] = {
    "avatar_explainer": frozenset(
        {CompositionLanguage.PRESENTER_CENTERED, CompositionLanguage.INFOGRAPHIC}
    ),
    "educational_lecture": frozenset(
        {CompositionLanguage.PRESENTER_CENTERED, CompositionLanguage.INFOGRAPHIC}
    ),
}


#: The single style-compatibility authority.
STYLE_COMPATIBILITY_REGISTRY = StyleCompatibilityRegistry()

# A documentary arc is served by an observed look or a recovered-record look, not
# by a dramatic grade. The table states that; nothing branches on it.
STYLE_COMPATIBILITY_REGISTRY.allow("documentary", "documentary_realism", "archival_history")
# An explanatory arc is served by clarity, or by a neutral surface that keeps the
# brand assets legible.
STYLE_COMPATIBILITY_REGISTRY.allow(
    "explanatory", "educational_clarity", "corporate_clean", "documentary_realism"
)
# A story arc is served by drama; an observed look also serves it when the story
# is told rather than performed.
STYLE_COMPATIBILITY_REGISTRY.allow(
    "story", "cinematic_drama", "documentary_realism", "archival_history"
)
# Short form is served by clarity, neutrality, or a forward look.
STYLE_COMPATIBILITY_REGISTRY.allow(
    "short_form", "educational_clarity", "corporate_clean", "future_tech"
)


__all__ = [
    "ARCHIVAL_HISTORY",
    "BUILTIN_VISUAL_STYLES",
    "CINEMATIC_DRAMA",
    "COMPOSITION_COMPATIBILITY",
    "CORPORATE_CLEAN",
    "DOCUMENTARY_REALISM",
    "EDUCATIONAL_CLARITY",
    "FUTURE_TECH",
    "STYLE_COMPATIBILITY_REGISTRY",
    "VISUAL_STYLE_REGISTRY",
    "StyleCompatibilityRegistry",
    "VisualStyleRegistry",
    "register_builtin_styles",
]
