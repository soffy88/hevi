"""S28 script layer: decide, write and review before spending on images/video.

The layer is deliberately text-only.  It reuses the ai_drama script schema
(``characters`` / ``scenes`` / ``beats`` / ``dialogue.kind``), the series cast
card, the hook gate and the S22 craft gates instead of owning a second
vocabulary.
"""

from __future__ import annotations

from .causality import check_causality, rewrite_chain
from .characters import build_cast_card, build_characters, check_characters
from .filmability import check_filmability
from .names import blacklist_chars, blacklist_names, blacklist_surnames, name_findings, pick_names
from .premise import evaluate_premise, parse_premise_text, premise_sentence
from .review import apply_selected, review_document
from .shortdrama import plan_short_drama
from .shortfilm import build_short_film
from .text import estimate_seconds, suggested_duration

__all__ = [
    "apply_selected",
    "blacklist_chars",
    "blacklist_names",
    "blacklist_surnames",
    "build_cast_card",
    "build_characters",
    "build_short_film",
    "check_causality",
    "check_characters",
    "check_filmability",
    "estimate_seconds",
    "evaluate_premise",
    "name_findings",
    "parse_premise_text",
    "pick_names",
    "plan_short_drama",
    "premise_sentence",
    "review_document",
    "rewrite_chain",
    "suggested_duration",
]
