"""HEVI P6.3 — Visual style model.

A ``VisualStyleGrammar`` declares how a video *looks and feels*: mood, colour
language, composition language, texture, motion and lighting. It is the third P6
grammar with real behaviour, and it consumes the narrative and presenter intents
rather than re-deriving either.

This is a semantic layer, not a rendering layer. It names *qualities* — "warm",
"archival", "studio-lit" — and never names a renderer, an asset, an image model,
a provider, a timeline or a shot. What a renderer does with "warm" is the
renderer's business, decided downstream by the existing authority.

Vocabulary discipline
---------------------
Every enum in this module names a visual or emotional *quality*. None names a
product, a platform, or a genre-of-marketing. ``COMMERCIAL_STYLE``,
``TIKTOK_STYLE``, ``AVATAR_STYLE`` and ``HISTORICAL_STYLE_ONLY`` are the failure
modes: a style named after a product means the vocabulary has started branching
on product identity, which is what this layer exists to prevent.
``test_no_product_specific_style_identifier`` enforces it across both the
enums and the registered grammars.

``category`` is the one field that could have become a back door — it groups
styles for lookup. It is a closed enum of *visual traditions*
(``DOCUMENTARY``, ``ARCHIVAL``, ``EDITORIAL``, ``CINEMATIC``, ``TECHNOLOGICAL``,
``BRAND_NEUTRAL``), not a product taxonomy, and it is deliberately not a
``product_type``.

Not an authority
----------------
P6.3 owns no pixel. ``hevi.renderers`` executes; P5.2's profile policies and
``CinematicRecipe`` supply the craft vocabulary. P6.3 states the intent those
authorities consume.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.production.p6.schema import ProductConstraint


class Mood(StrEnum):
    """Emotional register. General to any subject matter."""

    AUTHORITATIVE = "authoritative"
    EMOTIONAL = "emotional"
    DRAMATIC = "dramatic"
    EDUCATIONAL = "educational"
    FUTURISTIC = "futuristic"
    NOSTALGIC = "nostalgic"
    ENERGETIC = "energetic"
    MINIMAL = "minimal"


class ColorLanguage(StrEnum):
    """How colour behaves across the piece."""

    NATURAL = "natural"
    CINEMATIC = "cinematic"
    MONOCHROME = "monochrome"
    WARM = "warm"
    COOL = "cool"
    HIGH_CONTRAST = "high_contrast"


class CompositionLanguage(StrEnum):
    """How the frame is arranged."""

    DOCUMENTARY = "documentary"
    CINEMATIC = "cinematic"
    PRESENTER_CENTERED = "presenter_centered"
    INFOGRAPHIC = "infographic"
    OBSERVATIONAL = "observational"


class TextureLanguage(StrEnum):
    """Surface quality of the image."""

    REALISTIC = "realistic"
    ARCHIVAL = "archival"
    CLEAN = "clean"
    FUTURISTIC = "futuristic"


class LightingLanguage(StrEnum):
    """How the subject is lit."""

    NATURAL = "natural"
    STUDIO = "studio"
    DRAMATIC = "dramatic"
    SOFT = "soft"


class MotionLanguage(StrEnum):
    """How the frame moves.

    Named as *characteristics*, not as camera moves. P5.3 owns camera movement
    (``CinematicRecipe``, the ``path`` / ``focal_behavior`` primitives); a P6.3
    motion language states the felt quality of movement and the existing recipe
    authority decides what actually moves the camera.
    """

    RESTRAINED = "restrained"
    DELIBERATE = "deliberate"
    FLUID = "fluid"
    ENERGETIC = "energetic"
    STILL = "still"


class StyleCategory(StrEnum):
    """Visual tradition a style belongs to.

    A grouping for lookup, not a product taxonomy. Closed on purpose: a style
    whose category is not here is refused rather than filed under "other".
    """

    DOCUMENTARY = "documentary"
    ARCHIVAL = "archival"
    EDITORIAL = "editorial"
    CINEMATIC = "cinematic"
    TECHNOLOGICAL = "technological"
    BRAND_NEUTRAL = "brand_neutral"


@dataclass(frozen=True)
class VisualStyleGrammar:
    """A reusable, versioned visual style.

    Immutable and content-hashed. Declares qualities only — no renderer, no
    provider, no asset, no timeline, no shot.
    """

    id: str
    version: str
    name: str
    category: StyleCategory
    description: str = ""
    mood: Mood = Mood.MINIMAL
    color_language: ColorLanguage = ColorLanguage.NATURAL
    composition_language: CompositionLanguage = CompositionLanguage.DOCUMENTARY
    texture_language: TextureLanguage = TextureLanguage.REALISTIC
    motion_language: MotionLanguage = MotionLanguage.RESTRAINED
    lighting_language: LightingLanguage = LightingLanguage.NATURAL
    constraints: tuple[ProductConstraint, ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("VISUAL_STYLE_WITHOUT_ID:id required")
        if not self.version:
            raise ValueError(f"VISUAL_STYLE_WITHOUT_VERSION:{self.id}")
        if not self.name:
            raise ValueError(f"VISUAL_STYLE_WITHOUT_NAME:{self.id}")
        if not isinstance(self.category, StyleCategory):
            raise ValueError(
                f"UNKNOWN_STYLE_CATEGORY:{self.category!r}; the vocabulary is closed"
            )
        for label, value in (
            ("mood", self.mood),
            ("color_language", self.color_language),
            ("composition_language", self.composition_language),
            ("texture_language", self.texture_language),
            ("motion_language", self.motion_language),
            ("lighting_language", self.lighting_language),
        ):
            if not isinstance(value, StrEnum):
                raise ValueError(f"UNKNOWN_STYLE_LANGUAGE:{self.id}:{label}:{value!r}")

    @property
    def qualified_id(self) -> str:
        return f"{self.id}@v{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "mood": self.mood.value,
            "color_language": self.color_language.value,
            "composition_language": self.composition_language.value,
            "texture_language": self.texture_language.value,
            "motion_language": self.motion_language.value,
            "lighting_language": self.lighting_language.value,
            "constraints": [c.to_dict() for c in self.constraints],
        }

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def languages(self) -> dict[str, str]:
        """Every declared language, keyed by channel. Used for compatibility."""
        return {
            "mood": self.mood.value,
            "color_language": self.color_language.value,
            "composition_language": self.composition_language.value,
            "texture_language": self.texture_language.value,
            "motion_language": self.motion_language.value,
            "lighting_language": self.lighting_language.value,
        }


__all__ = [
    "ColorLanguage",
    "CompositionLanguage",
    "LightingLanguage",
    "Mood",
    "MotionLanguage",
    "StyleCategory",
    "TextureLanguage",
    "VisualStyleGrammar",
]
