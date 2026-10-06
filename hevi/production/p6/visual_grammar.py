"""HEVI P6.4 — Visual grammar: directive languages for the P5.3 cinematic engine.

P6.3 answered *what does this look like* (mood, palette, texture). P6.4 answers
*how is it shot and cut* — the five directive languages that tell P5.3's
retrieval what kind of shot is wanted.

Why this reuses P6.3's vocabulary
---------------------------------
``VisualGrammar`` declares ``motion_language``, ``composition_language`` and
``lighting_language`` — the same three concepts P6.3 already models. They are
**imported**, not redefined:

    from hevi.production.p6.visual_style.model import (
        CompositionLanguage, LightingLanguage, MotionLanguage,
    )

Two enums with the same name and different members would be two visual
authorities, and the compiler would spend its life arbitrating between them.
P6.4 therefore adds exactly two vocabularies of its own — ``CameraLanguage`` and
``EditingLanguage`` — and inherits the rest.

Where the two layers share an id (``documentary_realism``,
``educational_clarity``), they are two *projections* of one visual tradition: P6.3
projects mood/palette/texture, P6.4 projects camera/editing. That is a coherence
invariant rather than a coincidence, and
``VisualCompiler.compile()`` enforces it — pass a P6.3 ``VisualStyleIntent``
alongside and a disagreement on any shared language raises
``VISUAL_GRAMMAR_STYLE_CONFLICT`` instead of silently preferring one layer.

Why camera_language is coarse
-----------------------------
P5.3's ``CinematicRecipe`` owns the concrete camera primitives (``camera_behavior``,
``path``, ``focal_behavior``, ``entry_behavior``). A P6.4 vocabulary that
enumerated ``dolly``/``pan``/``crane``/``orbit`` would be a second camera
vocabulary competing with the recipes it is supposed to feed. So
``CameraLanguage`` names *directive qualities* — observed, stable, directed — and
refines them. P5.3 decides what the camera actually does.

No product vocabulary
---------------------
``VisualGrammar`` carries no ``product_type`` and no ``P01_*``/``P02_*`` literal.
Four general grammars ship: ``documentary_realism``, ``dramatic_reconstruction``,
``educational_clarity``, ``commercial_clean``. Deliberately *not* shipped:
``history_visual_grammar``, ``avatar_visual_grammar``,
``science_visual_grammar`` — a grammar named after a product is a pipeline named
after a product, which is the failure this whole layer exists to prevent.
``P03 -> historical_camera()`` is the specific anti-pattern the spec names, and
``test_mutation_injected_product_branch_into_real_grammar_must_fail`` kills it.

This module defines no shot, no motion plan, no timeline and no renderer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p6.schema import ProductConstraint
from hevi.production.p6.visual_style.model import (
    CompositionLanguage,
    LightingLanguage,
    MotionLanguage,
)

_C = ProductConstraint


class CameraLanguage(StrEnum):
    """Directive camera quality. Never a concrete move.

    Coarse on purpose: P5.3's recipes refine these into ``dolly``/``pan``/``path``
    primitives. Naming a primitive here would create a second camera vocabulary.
    """

    OBSERVED = "observed"
    STABLE = "stable"
    DIRECTED = "directed"
    ENERGETIC = "energetic"
    INTIMATE = "intimate"
    DISCOVERING = "discovering"


class EditingLanguage(StrEnum):
    """Directive cutting rhythm."""

    CONTINUOUS = "continuous"
    ASSEMBLED = "assembled"
    LONG_TAKE = "long_take"
    ACCELERATING = "accelerating"
    STEPPED = "stepped"


@dataclass(frozen=True)
class VisualGrammar:
    """A shared, versioned set of visual directive languages.

    Immutable and content-hashed. Declares intent for P5.3; executes nothing.
    """

    visual_grammar_id: str
    version: str
    name: str
    description: str = ""
    camera_language: CameraLanguage = CameraLanguage.STABLE
    motion_language: MotionLanguage = MotionLanguage.RESTRAINED
    composition_language: CompositionLanguage = CompositionLanguage.DOCUMENTARY
    lighting_language: LightingLanguage = LightingLanguage.NATURAL
    editing_language: EditingLanguage = EditingLanguage.CONTINUOUS
    compatible_beat_roles: tuple[str, ...] = ()
    constraints: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.visual_grammar_id:
            raise ValueError("VISUAL_GRAMMAR_WITHOUT_ID:id required")
        if not self.version:
            raise ValueError(f"VISUAL_GRAMMAR_WITHOUT_VERSION:{self.visual_grammar_id}")
        if not self.name:
            raise ValueError(f"VISUAL_GRAMMAR_WITHOUT_NAME:{self.visual_grammar_id}")
        for label, value, vocabulary in (
            ("camera_language", self.camera_language, CameraLanguage),
            ("motion_language", self.motion_language, MotionLanguage),
            ("composition_language", self.composition_language, CompositionLanguage),
            ("lighting_language", self.lighting_language, LightingLanguage),
            ("editing_language", self.editing_language, EditingLanguage),
        ):
            if not isinstance(value, vocabulary):
                raise ValueError(
                    f"UNKNOWN_VISUAL_LANGUAGE:{self.visual_grammar_id}:{label}:{value!r}"
                )
        for role in self.compatible_beat_roles:
            if not role:
                raise ValueError(
                    f"INVALID_BEAT_ROLE:{self.visual_grammar_id}:{role!r}"
                )

    @property
    def qualified_id(self) -> str:
        return f"{self.visual_grammar_id}@v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_grammar_id": self.visual_grammar_id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "camera_language": self.camera_language.value,
            "motion_language": self.motion_language.value,
            "composition_language": self.composition_language.value,
            "lighting_language": self.lighting_language.value,
            "editing_language": self.editing_language.value,
            "compatible_beat_roles": list(self.compatible_beat_roles),
            "constraints": [c.to_dict() for c in self.constraints],
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def languages(self) -> dict[str, str]:
        """The five declared directive languages."""
        return {
            "camera_language": self.camera_language.value,
            "motion_language": self.motion_language.value,
            "composition_language": self.composition_language.value,
            "lighting_language": self.lighting_language.value,
            "editing_language": self.editing_language.value,
        }


# ── Built-in visual grammars ────────────────────────────────────────────

DOCUMENTARY_REALISM = VisualGrammar(
    visual_grammar_id="documentary_realism",
    version="1.0.0",
    name="Documentary Realism",
    description="Observed camera, continuous cutting, available light. The frame was there.",
    camera_language=CameraLanguage.OBSERVED,
    motion_language=MotionLanguage.RESTRAINED,
    composition_language=CompositionLanguage.DOCUMENTARY,
    lighting_language=LightingLanguage.NATURAL,
    editing_language=EditingLanguage.CONTINUOUS,
    compatible_beat_roles=("ESTABLISH", "FOLLOW", "DETAIL", "EXPLAIN"),
    constraints=(
        _C(key="camera_directive", value="observed", rationale="an observed camera does not perform"),
        _C(key="editing_directive", value="continuous", rationale="cutting reveals, it does not announce"),
    ),
)

DRAMATIC_RECONSTRUCTION = VisualGrammar(
    visual_grammar_id="dramatic_reconstruction",
    version="1.0.0",
    name="Dramatic Reconstruction",
    description="Directed camera with deliberate reveals. Staged, disclosed as staged.",
    camera_language=CameraLanguage.DIRECTED,
    motion_language=MotionLanguage.DELIBERATE,
    composition_language=CompositionLanguage.CINEMATIC,
    lighting_language=LightingLanguage.DRAMATIC,
    editing_language=EditingLanguage.LONG_TAKE,
    compatible_beat_roles=("ESTABLISH", "REVEAL", "PAYOFF", "TRANSITION"),
    constraints=(
        _C(key="camera_directive", value="directed", rationale="the frame is composed for effect"),
        _C(key="reconstruction_disclosure", value="required", rationale="staged material must say so"),
    ),
)

EDUCATIONAL_CLARITY = VisualGrammar(
    visual_grammar_id="educational_clarity",
    version="1.0.0",
    name="Educational Clarity",
    description="Stable instructional framing, assembled cuts, even light.",
    camera_language=CameraLanguage.STABLE,
    motion_language=MotionLanguage.RESTRAINED,
    composition_language=CompositionLanguage.INFOGRAPHIC,
    lighting_language=LightingLanguage.STUDIO,
    editing_language=EditingLanguage.ASSEMBLED,
    compatible_beat_roles=("EXPLAIN", "COMPARE", "DETAIL", "REVEAL"),
    constraints=(
        _C(key="camera_directive", value="stable", rationale="a moving frame competes with the explanation"),
        _C(key="legibility_first", value="true", rationale="clarity outranks mood in instruction"),
    ),
)

COMMERCIAL_CLEAN = VisualGrammar(
    visual_grammar_id="commercial_clean",
    version="1.0.0",
    name="Commercial Clean",
    description="Controlled camera with an energy floor. Brand assets carry the identity.",
    camera_language=CameraLanguage.ENERGETIC,
    motion_language=MotionLanguage.FLUID,
    composition_language=CompositionLanguage.PRESENTER_CENTERED,
    lighting_language=LightingLanguage.SOFT,
    editing_language=EditingLanguage.ACCELERATING,
    compatible_beat_roles=("ESTABLISH", "REVEAL", "PAYOFF", "FOLLOW"),
    constraints=(
        _C(key="camera_directive", value="energetic", rationale="the beat needs momentum"),
        _C(key="brand_neutral", value="true", rationale="the brand supplies identity, not the camera"),
    ),
)

BUILTIN_VISUAL_GRAMMARS: tuple[VisualGrammar, ...] = (
    DOCUMENTARY_REALISM,
    DRAMATIC_RECONSTRUCTION,
    EDUCATIONAL_CLARITY,
    COMMERCIAL_CLEAN,
)

#: Grammar ids explicitly refused. Naming what must not exist is part of the
#: contract: a future contributor who reaches for these gets a test failure.
FORBIDDEN_VISUAL_GRAMMAR_IDS: tuple[str, ...] = (
    "history_visual_grammar",
    "avatar_visual_grammar",
    "science_visual_grammar",
    "historical_visual_grammar",
    "commercial_visual_grammar",
    "short_form_visual_grammar",
)


# ── Registry ────────────────────────────────────────────────────────────


def _split_qualified(ref: str) -> tuple[str, str | None]:
    if "@" not in ref:
        return ref, None
    base, _, version = ref.partition("@")
    if not base or not version:
        return ref, None
    if version.startswith("v") and len(version) > 1:
        version = version[1:]
    return base, version


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in version.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            return (0, *parts, 0)
    return tuple(parts)


class VisualGrammarRegistry:
    """The single authority for visual grammars.

    Maps ``visual_grammar_id -> VisualGrammar`` and nothing else. It has no
    product dimension: there is no path from a ``product_type`` to a visual
    grammar here, and ``test_registry_exposes_no_product_dimension`` pins that.
    """

    def __init__(self) -> None:
        self._grammars: dict[str, VisualGrammar] = {}
        self._versions: dict[str, list[str]] = {}

    @staticmethod
    def _key(grammar_id: str, version: str) -> str:
        return f"{grammar_id}@v{version}"

    def register(self, grammar: VisualGrammar) -> VisualGrammar:
        if not isinstance(grammar, VisualGrammar):
            raise ValueError(f"NOT_A_VISUAL_GRAMMAR:{type(grammar).__name__}")
        key = grammar.qualified_id
        if key in self._grammars:
            raise ValueError(f"VISUAL_GRAMMAR_IMMUTABLE:{key} already registered")
        self._grammars[key] = grammar
        self._versions.setdefault(grammar.visual_grammar_id, []).append(grammar.version)
        return grammar

    def get(self, ref: str, version: str | None = None) -> VisualGrammar | None:
        grammar_id, embedded = _split_qualified(ref)
        target = version or embedded
        if target:
            direct = self._grammars.get(self._key(grammar_id, target))
            if direct is not None:
                return direct
            if target.startswith("v") and len(target) > 1:
                return self._grammars.get(self._key(grammar_id, target[1:]))
            return None
        versions = self._versions.get(grammar_id, [])
        if not versions:
            return None
        latest = sorted(versions, key=_version_key)[-1]
        return self._grammars.get(self._key(grammar_id, latest))

    def resolve(self, ref: str, version: str | None = None) -> VisualGrammar:
        grammar = self.get(ref, version)
        if grammar is None:
            raise KeyError(f"UNKNOWN_VISUAL_GRAMMAR:{ref}")
        return grammar

    def list_all(self) -> list[VisualGrammar]:
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
            return False, [f"VISUAL_GRAMMAR_NOT_FOUND:{ref}"]
        errors: list[str] = []
        for channel, value in sorted(grammar.languages().items()):
            if not value:
                errors.append(f"EMPTY_VISUAL_LANGUAGE:{channel}")
        if grammar.visual_grammar_id in FORBIDDEN_VISUAL_GRAMMAR_IDS:
            errors.append(f"PRODUCT_NAMED_VISUAL_GRAMMAR:{grammar.visual_grammar_id}")
        return (not errors), errors

    def validate_all(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for grammar_id in self.list_ids():
            ok, grammar_errors = self.validate(grammar_id)
            if not ok:
                errors.extend(f"{grammar_id}:{e}" for e in grammar_errors)
        return (not errors), errors

    def to_dict(self) -> dict[str, Any]:
        return {key: g.to_dict() for key, g in sorted(self._grammars.items())}


#: The single visual grammar authority.
VISUAL_GRAMMAR_REGISTRY = VisualGrammarRegistry()


def register_builtin_visual_grammars(*, force: bool = False) -> list[str]:
    """Register the four built-ins. Idempotent, never overwrites silently."""
    registered: list[str] = []
    for grammar in BUILTIN_VISUAL_GRAMMARS:
        existing = VISUAL_GRAMMAR_REGISTRY.get(grammar.visual_grammar_id, grammar.version)
        if existing is not None and not force:
            registered.append(grammar.qualified_id)
            continue
        if existing is not None and existing.content_hash() != grammar.content_hash():
            raise ValueError(
                f"VISUAL_GRAMMAR_IMMUTABLE:{grammar.qualified_id} already registered "
                "with different content"
            )
        VISUAL_GRAMMAR_REGISTRY.register(grammar)
        registered.append(grammar.qualified_id)
    return registered


register_builtin_visual_grammars()


# ── Narrative compatibility (data) ──────────────────────────────────────


class VisualGrammarCompatibility:
    """Which visual grammars may serve a given narrative / presenter pair.

    Data, keyed by grammar id. Extends P6.3's
    ``STYLE_COMPATIBILITY_REGISTRY`` with the camera and editing dimension,
    because a style may look right and still be unfilmable as directed — an
    energetic camera under a long-take documentary edit contradicts itself.
    """

    def __init__(self) -> None:
        self._table: dict[str, frozenset[str]] = {}

    def allow(self, narrative_grammar_id: str, *grammar_ids: str) -> None:
        if not narrative_grammar_id:
            raise ValueError("VISUAL_COMPATIBILITY_WITHOUT_NARRATIVE_ID:id required")
        for grammar_id in grammar_ids:
            if not grammar_id:
                raise ValueError("VISUAL_COMPATIBILITY_WITHOUT_GRAMMAR_ID:id required")
        existing = self._table.get(narrative_grammar_id, frozenset())
        self._table[narrative_grammar_id] = existing | frozenset(grammar_ids)

    def allowed(self, narrative_grammar_id: str) -> frozenset[str] | None:
        return self._table.get(narrative_grammar_id)

    def is_compatible(self, narrative_grammar_id: str, grammar_id: str) -> bool:
        permitted = self.allowed(narrative_grammar_id)
        return True if permitted is None else grammar_id in permitted

    def list_narratives(self) -> list[str]:
        return sorted(self._table)

    def validate_all(self) -> tuple[bool, list[str]]:
        errors = [
            f"UNKNOWN_GRAMMAR_IN_COMPATIBILITY:{narrative_id}->{grammar_id}"
            for narrative_id, grammars in sorted(self._table.items())
            for grammar_id in sorted(grammars)
            if not VISUAL_GRAMMAR_REGISTRY.has(grammar_id)
        ]
        return (not errors), errors

    def to_dict(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sorted(self._table.items())}


#: The single visual-grammar compatibility authority.
VISUAL_GRAMMAR_COMPATIBILITY = VisualGrammarCompatibility()

VISUAL_GRAMMAR_COMPATIBILITY.allow(
    "documentary", "documentary_realism", "dramatic_reconstruction"
)
VISUAL_GRAMMAR_COMPATIBILITY.allow(
    "story", "dramatic_reconstruction", "documentary_realism"
)
VISUAL_GRAMMAR_COMPATIBILITY.allow("explanatory", "educational_clarity", "commercial_clean")
VISUAL_GRAMMAR_COMPATIBILITY.allow("short_form", "commercial_clean", "educational_clarity")

__all__ = [
    "BUILTIN_VISUAL_GRAMMARS",
    "COMMERCIAL_CLEAN",
    "DOCUMENTARY_REALISM",
    "DRAMATIC_RECONSTRUCTION",
    "EDUCATIONAL_CLARITY",
    "FORBIDDEN_VISUAL_GRAMMAR_IDS",
    "VISUAL_GRAMMAR_COMPATIBILITY",
    "VISUAL_GRAMMAR_REGISTRY",
    "CameraLanguage",
    "CompositionLanguage",
    "EditingLanguage",
    "LightingLanguage",
    "MotionLanguage",
    "VisualGrammar",
    "VisualGrammarCompatibility",
    "VisualGrammarRegistry",
    "register_builtin_visual_grammars",
]
