"""Shot recipe card library (video-shotcraft import).

Data asset: the 124 shot recipe cards from Vincentwei1021/video-shotcraft
(Apache-2.0) imported verbatim as Markdown under ``shotcraft_data/cards/``
plus a parsed index (``shotcraft_data/shotcraft_index.json``, rebuilt by
``shotcraft_data/build_shotcraft_index.py``).  Only the card *data* was
imported -- none of the upstream Remotion demo code; each card's index
entry keeps its upstream ``demos/...`` path as a reference pointer into
the checkout at ``~/projects/_refs/video-shotcraft``.

Relation to the rest of shotlang: ``ShotLangSpec`` describes one shot of
a concrete project (framing / continuity / acceptance); a recipe card is
the reusable motion vocabulary a spec can draw its ``camera_movement``
from.  ``MotionLibraryBridge`` (motion_library.py) is a 4-entry huashu
stub; :func:`motion_library_entries` exposes the recipe cards in that
same ``{id, name, desc}`` shape so the stub can be backed by real data
without changing its interface.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "shotcraft_data"
INDEX_PATH = DATA_DIR / "shotcraft_index.json"

SHOTCRAFT_SOURCE_URL = "https://github.com/Vincentwei1021/video-shotcraft"
UPSTREAM_COMMIT = "43bd349a136651865ecfa6ea1cf012f6e957d304"
ATTRIBUTION = (
    "Shot recipe cards by Vincentwei1021/video-shotcraft "
    "(https://github.com/Vincentwei1021/video-shotcraft), "
    "Apache License 2.0."
)


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def counts() -> dict[str, Any]:
    return load_index()["counts"]


def list_cards(
    category: str = "",
    query: str = "",
    energy: str = "",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List/filter index entries. ``query`` matches name, one-liner,
    applies-to, tags and category (case-insensitive substring)."""
    q = query.strip().lower()
    out: list[dict[str, Any]] = []
    for card in load_index()["cards"]:
        if category and card["category"] != category:
            continue
        if energy and energy not in card.get("energy", ""):
            continue
        if q:
            haystack = " ".join(
                str(card.get(k, ""))
                for k in ("name", "category", "one_liner", "applies_to", "tags")
            ).lower()
            if q not in haystack:
                continue
        out.append(card)
        if len(out) >= limit:
            break
    return out


def get_card(name: str) -> dict[str, Any]:
    """Return one card's index entry plus its full Markdown text.

    Raises ``KeyError`` for an unknown card name -- never a fake card.
    """
    for card in load_index()["cards"]:
        if card["name"] == name:
            path = DATA_DIR / card["file"]
            return {**card, "markdown": path.read_text(encoding="utf-8")}
    raise KeyError(f"unknown shot recipe card: {name}")


def motion_library_entries() -> list[dict[str, str]]:
    """Recipe cards in MotionLibraryBridge's ``{id, name, desc}`` shape."""
    return [
        {
            "id": card["name"],
            "name": card["name"],
            "desc": card["one_liner"],
            "category": card["category"],
        }
        for card in load_index()["cards"]
    ]
