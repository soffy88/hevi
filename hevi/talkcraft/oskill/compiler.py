"""Camera variation and pause-aware card selection."""

from __future__ import annotations

from typing import Any

from hevi.motion.recipe_card import build_shotcraft_library


def choose_motion_cards(cues: list[dict[str, Any]], *, card_limit: int = 78) -> list[dict[str, Any]]:
    library = list(build_shotcraft_library().values())
    cards = [card for card in library if card.category in {"camera", "rhythm", "interaction", "typography"}]
    if not cards:
        return []
    selected: list[dict[str, Any]] = []
    previous_category = ""
    for index, cue in enumerate(cues):
        card = next((item for item in cards if item.category != previous_category), cards[index % len(cards)])
        previous_category = card.category
        selected.append(
            {
                "cue_id": str(cue.get("cue_id") or index),
                "card": card.name,
                "category": card.category,
                "duration_s": round(max(0.2, float(cue.get("end_s", 0)) - float(cue.get("start_s", 0))), 3),
                "camera_reason": "pause/semantic beat" if index else "opening beat",
            }
        )
        if len(selected) >= card_limit:
            break
    return selected


__all__ = ["choose_motion_cards"]
