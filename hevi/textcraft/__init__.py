"""Textcraft: deterministic style profiling, style transfer, de-AI polish.

Clean-room implementation of two text abilities:

* style work — :mod:`hevi.textcraft.style` extracts a statistical style
  profile from a sample (sentence/paragraph length distributions, punctuation
  and function-word frequencies, tone markers) and transfers that style onto
  new text through an injected rewrite function.
* humanize — :mod:`hevi.textcraft.humanize` strips AI-template phrasing and
  evens out machine-typical rhythm with pure, deterministic functions.
"""

from __future__ import annotations

from .humanize import (
    CLICHE_REPLACEMENTS,
    COLLOQUIAL_REPLACEMENTS,
    count_cliches,
    humanize_text,
)
from .style import (
    build_style_instructions,
    extract_style_profile,
    profile_distance,
    split_sentences,
    style_transfer,
)

__all__ = [
    "CLICHE_REPLACEMENTS",
    "COLLOQUIAL_REPLACEMENTS",
    "count_cliches",
    "humanize_text",
    "build_style_instructions",
    "extract_style_profile",
    "profile_distance",
    "split_sentences",
    "style_transfer",
]
