"""HEVI P6.3 — Visual style semantics.

A subpackage rather than three loose modules, because the visual style layer has
three distinct authorities that are easy to conflate:

``model``
    ``VisualStyleGrammar`` and the closed style vocabulary (mood, colour,
    composition, texture, motion, lighting). No product vocabulary at all.

``registry``
    ``VISUAL_STYLE_REGISTRY`` (what each style *is*),
    ``STYLE_COMPATIBILITY_REGISTRY`` (which styles may serve which narrative),
    and ``COMPOSITION_COMPATIBILITY`` (which frames may carry which performance).

``compiler``
    ``VisualStyleCompiler``, which turns a narrative intent plus a presenter
    intent plus a style grammar into a ``VisualStyleIntent``.

Forbidden authorities
---------------------
P6.3 owns no renderer, no asset generator, no image model, no provider, no
timeline and no shot planning. It states the visual intent that those existing
authorities consume. The forbidden module prefixes are unimported here and
guarded by ``tests/test_p6_3_visual_style.py::test_no_forbidden_import``.
"""

from __future__ import annotations

from hevi.production.p6.visual_style.compiler import (
    VisualStyleCompiler,
    VisualStyleIntent,
    VisualStyleValidationResult,
)
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
from hevi.production.p6.visual_style.registry import (
    ARCHIVAL_HISTORY,
    BUILTIN_VISUAL_STYLES,
    CINEMATIC_DRAMA,
    COMPOSITION_COMPATIBILITY,
    CORPORATE_CLEAN,
    DOCUMENTARY_REALISM,
    EDUCATIONAL_CLARITY,
    FUTURE_TECH,
    STYLE_COMPATIBILITY_REGISTRY,
    VISUAL_STYLE_REGISTRY,
    StyleCompatibilityRegistry,
    VisualStyleRegistry,
    register_builtin_styles,
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
    "ColorLanguage",
    "CompositionLanguage",
    "LightingLanguage",
    "Mood",
    "MotionLanguage",
    "StyleCategory",
    "StyleCompatibilityRegistry",
    "TextureLanguage",
    "VISUAL_STYLE_REGISTRY",
    "VisualStyleCompiler",
    "VisualStyleGrammar",
    "VisualStyleIntent",
    "VisualStyleRegistry",
    "VisualStyleValidationResult",
    "register_builtin_styles",
]
