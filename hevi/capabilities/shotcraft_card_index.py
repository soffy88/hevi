"""Shotcraft card index (``video.shotcraft_card_index``).

Identity index only. The 124 tuned upstream shot cards are listed
by name, category, style keys, and provenance references, loaded
from the sibling ``shotcraft_card_index.json``. Purpose glosses are
derived mechanically from card names only; upstream purpose prose,
tuned parameter values, pitfall text, and demo code were
intentionally not copied. Every entry records
``verified_by_hevi_render: false``: this index asserts identity and
provenance, never that hevi has rendered a card. The hevi-side
synthesized 152-name catalogue in ``hevi.motion.recipe_card`` is a
separate artefact and must never be confused with this index: the
two name sets overlap only where the synthesized catalogue reused a
name, and only membership in this index counts as a tuned card. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_INDEX_PATH = Path(__file__).with_name("shotcraft_card_index.json")
_INDEX_CACHE: dict[str, Any] | None = None

CARD_CATEGORIES: tuple[str, ...] = (
    "camera",
    "data",
    "effects",
    "interaction",
    "opening",
    "outro",
    "rhythm",
    "transition",
    "typography",
    "ui-entrance",
)


def _load_index() -> dict[str, Any]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        _INDEX_CACHE = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    return _INDEX_CACHE


def list_shotcraft_cards(category: str | None = None) -> list[dict[str, Any]]:
    """Return index entries, optionally filtered by category."""
    cards = _load_index()["cards"]
    if category is None:
        return [dict(c) for c in cards]
    return [dict(c) for c in cards if c["category"] == category]


def get_shotcraft_card(name: str) -> dict[str, Any] | None:
    """Return one index entry by name, or None when absent."""
    for card in _load_index()["cards"]:
        if card["name"] == name:
            return dict(card)
    return None


def check_card_index() -> dict[str, Any]:
    """Validate the index file itself. Returns a report; never raises."""
    issues: list[str] = []
    index = _load_index()
    cards = index.get("cards")
    if not isinstance(cards, list):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": ["cards_missing"],
            "card_count": 0,
        }
    names = [c.get("name") for c in cards if isinstance(c, dict)]
    if len(names) != len(set(names)):
        issues.append("duplicate_names")
    if len(cards) != 124:
        issues.append(f"card_count_not_124:{len(cards)}")
    for card in cards:
        if not isinstance(card, dict):
            issues.append("entry_not_object")
            continue
        if card.get("category") not in CARD_CATEGORIES:
            issues.append(f"unknown_category:{card.get('name')}")
        if not str(card.get("source_ref", "")).startswith("references/shots/"):
            issues.append(f"source_ref_shape:{card.get('name')}")
        if not str(card.get("demo_ref", "")).startswith("demos/"):
            issues.append(f"demo_ref_shape:{card.get('name')}")
        if card.get("verified_by_hevi_render") is not False:
            issues.append(f"verified_flag_wrong:{card.get('name')}")
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "card_count": len(cards),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    category = params.get("category")
    report = {
        "index_check": check_card_index(),
        "cards": list_shotcraft_cards(category),
        "category": category,
    }
    report_path = out_dir / "shotcraft_card_index.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["index_check"]["verdict"]},
    )


def register_shotcraft_card_index_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.shotcraft_card_index",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "category": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Shotcraft card index: identity and provenance for "
                "the 124 tuned upstream shot cards (names, "
                "categories, style keys, source/demo refs); "
                "purpose glosses are name-derived only and no card "
                "is recorded as rendered by hevi."
            ),
        )
    )
    return ["video.shotcraft_card_index"]


__all__ = [
    "CARD_CATEGORIES",
    "list_shotcraft_cards",
    "get_shotcraft_card",
    "check_card_index",
    "register_shotcraft_card_index_capabilities_once",
]
