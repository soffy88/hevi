"""Portrait prompt vocabulary index: load, look up, search.

Data: ``portrait_vocab_index.json`` next to this module -- 66 entries in
8 categories (video_micro 6, posture 8, hair_head 8, hands 9, motion 8,
sitting 8, standing 9, gaze 10), transcribed verbatim from the image
pages Soffy forwarded on 2026-10-23 (archive:
``~/workspace/references/portrait-prompt-vocab/VOCAB.md``; rebuild with
``build_portrait_index.py`` in this package).  Every entry carries
``id``, ``category``, ``zh``, ``en``, ``how`` (the concrete, executable
way to write it) and ``feeling``.  The source has no expression
category (the author left expressions to free description); none is
invented here.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_INDEX_PATH = Path(__file__).with_name("portrait_vocab_index.json")
_PHRASING_PATH = Path(__file__).with_name("PHRASING.md")
_RULE_HEADING_RE = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)

CATEGORIES = (
    "video_micro",
    "posture",
    "hair_head",
    "hands",
    "motion",
    "sitting",
    "standing",
    "gaze",
)


class PortraitVocabError(ValueError):
    """Unknown entry/category or a malformed vocabulary request."""


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    if not _INDEX_PATH.exists():
        raise PortraitVocabError(
            f"portrait vocab index missing at {_INDEX_PATH}; rebuild it "
            "with hevi/image/portrait_vocab/build_portrait_index.py"
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
            raise PortraitVocabError(
                f"unknown portrait vocab category: {category!r} "
                f"(want one of {', '.join(CATEGORIES)})"
            )
        items = [e for e in items if e["category"] == category]
    return [dict(e) for e in items]


def get_entry(raw: str) -> dict[str, Any]:
    """Resolve an entry by id, Chinese name or English phrase."""
    text = str(raw).strip()
    if not text:
        raise PortraitVocabError("empty portrait vocab entry reference")
    for entry in load_index()["entries"]:
        if (
            entry["id"].upper() == text.upper()
            or entry["zh"] == text
            or entry["en"].lower() == text.lower()
        ):
            return dict(entry)
    raise PortraitVocabError(
        f"unknown portrait vocab entry: {raw!r} (use a listed id like "
        "GA-01, a Chinese name like 托腮, or an English phrase like "
        "'holding a cup')"
    )


def phrasing_path() -> Path:
    """The phrasing spec (PHRASING.md) shipped with this package."""
    return _PHRASING_PATH


@lru_cache(maxsize=1)
def phrasing_rules() -> list[dict[str, Any]]:
    """Rule titles of the phrasing spec, parsed from PHRASING.md.

    The spec is the human/agent-facing distillation of this vocabulary:
    how to *write* portrait descriptions so they are executable
    (support points, direction/amplitude/stop, gaze/face/body axes,
    one pick per group, person before scene...).  Agents writing
    portrait prompts should read the doc itself; this returns its
    table of contents for capability responses.
    """
    if not _PHRASING_PATH.exists():
        raise PortraitVocabError(
            f"phrasing spec missing at {_PHRASING_PATH}"
        )
    text = _PHRASING_PATH.read_text(encoding="utf-8")
    return [
        {"n": int(m.group(1)), "title": m.group(2).strip()}
        for m in _RULE_HEADING_RE.finditer(text)
    ]


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
