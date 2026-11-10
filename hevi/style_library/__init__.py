"""Handraw-style library integration (catalog, recommendation, covers, locks).

Data: ``hevi/image/handraw_data/handraw_index.json`` (built from
yang0/handraw-style, MIT + attribution).  This package is the product-facing
layer: search, automatic recommendation, theme palettes, layout routing,
cover / article illustration planning, colour lock + drift check, and
bridges into handdraw / comic narration / ai_drama / warm-gold explainer /
S24 repurpose.  The upstream index remains the single source of truth.
"""

from __future__ import annotations

ATTRIBUTION = (
    "风格库来自 yang0/handraw-style "
    "(https://github.com/yang0/handraw-style)，MIT License + 署名要求。"
)
ATTRIBUTION_URL = "https://github.com/yang0/handraw-style"
ATTRIBUTION_AUTHOR = "yang0"
LICENSE_NOTE = "MIT License with Attribution Requirement"

__all__ = [
    "ATTRIBUTION",
    "ATTRIBUTION_URL",
    "ATTRIBUTION_AUTHOR",
    "LICENSE_NOTE",
]
