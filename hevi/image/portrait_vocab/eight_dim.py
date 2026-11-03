"""Eight-dimension portrait extension vocabulary: load, look up, search.

Data: ``eight_dim_vocab_index.json`` next to this module -- 32 entries
in 4 categories (fabric 8, skin_light 8, lens_optics 8,
micro_expression 8), restated in our own words from generic
photographic language (focal lengths, apertures, lighting terms,
fabric names).  This is an *extension* to the verbatim 66-entry
``portrait_vocab_index.json``: that transcription is left untouched
(the source pages are quoted verbatim there), and these entries
follow the same entry shape (``id``/``category``/``zh``/``en``/
``how``/``feeling``).

The four categories cover four of the eight assembly dimensions
(fabric, light/skin, lens optics, micro-expression).  The other
dimensions (anchoring, environment, restraint, negatives) are
caller-supplied text judged by the ``qa.*`` gates, not vocabulary
picks.  Adult portraits only.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_INDEX_PATH = Path(__file__).with_name("eight_dim_vocab_index.json")

CATEGORIES = (
    "fabric",
    "skin_light",
    "lens_optics",
    "micro_expression",
)

# Assembly dimension -> extension category (dimensions without a
# category take caller-supplied text instead of a vocabulary pick).
DIMENSION_CATEGORIES: dict[str, str] = {
    "fabric": "fabric",
    "expression": "micro_expression",
    "lens": "lens_optics",
    "light": "skin_light",
}

DIMENSIONS: tuple[str, ...] = (
    "anchoring",
    "fabric",
    "expression",
    "lens",
    "light",
    "environment",
    "restraint",
    "negatives",
)


class EightDimVocabError(ValueError):
    """Unknown entry/category or a malformed extension-vocabulary request."""


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    if not _INDEX_PATH.exists():
        raise EightDimVocabError(
            f"eight-dim vocab index missing at {_INDEX_PATH}"
        )
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def counts() -> dict[str, int]:
    return dict(load_index()["counts"])


def list_categories() -> list[str]:
    return list(CATEGORIES)


def entries(category: str = "") -> list[dict[str, Any]]:
    items = load_index()["entries"]
    if category:
        if category not in CATEGORIES:
            raise EightDimVocabError(
                f"unknown eight-dim category: {category!r} "
                f"(want one of {', '.join(CATEGORIES)})"
            )
        items = [e for e in items if e["category"] == category]
    return [dict(e) for e in items]


def get_entry(raw: Any) -> dict[str, Any]:
    """Resolve an entry by id, Chinese name, or English phrase."""
    text = str(raw).strip()
    if not text:
        raise EightDimVocabError("empty eight-dim entry reference")
    for entry in load_index()["entries"]:
        if (
            entry["id"].upper() == text.upper()
            or entry["zh"] == text
            or entry["en"].lower() == text.lower()
        ):
            return dict(entry)
    raise EightDimVocabError(
        f"unknown eight-dim entry: {raw!r} (use a listed id like "
        "FA-01, a Chinese name like 生丝上衣, or an English phrase "
        "like 'raw silk top')"
    )


def search(
    category: str = "", *, query: str = "", limit: int = 200
) -> list[dict[str, Any]]:
    """Filter entries by category and free-text query (zh/en/how/feeling)."""
    items = entries(category)
    q = query.strip().lower()
    if q:
        items = [
            e
            for e in items
            if q in json.dumps(e, ensure_ascii=False).lower()
        ]
    return items[:limit]


def assemble_eight_dim(
    picks: dict[str, dict[str, Any]],
    *,
    identity: str = "",
    anchoring: str = "",
    environment: str = "",
    scene: str = "",
    framing: str = "",
    negatives: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble one eight-dimension prompt from resolved entries.

    ``picks`` maps dimension name (fabric/expression/lens/light) to a
    resolved entry dict.  Text order is person first, scene second:
    identity, anchoring, then each pick's ``how`` expansion in
    dimension order, then environment, scene, framing.  Negatives are
    returned as a separate ``negative_prompt`` field, never folded
    into the main prompt.
    """
    order = ("fabric", "expression", "lens", "light")
    picked = [picks[d] for d in order if d in picks]
    zh_parts: list[str] = []
    if identity.strip():
        zh_parts.append(identity.strip())
    if anchoring.strip():
        zh_parts.append(anchoring.strip())
    zh_parts.extend(e["how"] for e in picked)
    if environment.strip():
        zh_parts.append(environment.strip())
    if scene.strip():
        zh_parts.append(scene.strip())
    if framing.strip():
        zh_parts.append(framing.strip())
    prompt_en = ", ".join(e["en"] for e in picked)
    neg_list = [str(n).strip() for n in (negatives or []) if str(n).strip()]
    return {
        "prompt_zh": "；".join(zh_parts),
        "prompt_en": prompt_en,
        "negative_prompt": ", ".join(neg_list),
        "entry_ids": [e["id"] for e in picked],
        "entries": picked,
    }


__all__ = [
    "CATEGORIES",
    "DIMENSIONS",
    "DIMENSION_CATEGORIES",
    "EightDimVocabError",
    "assemble_eight_dim",
    "counts",
    "entries",
    "get_entry",
    "list_categories",
    "load_index",
    "search",
]
