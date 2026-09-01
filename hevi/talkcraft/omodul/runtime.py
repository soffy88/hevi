"""Compile local voice cues to an editable motion plan; rendering is separate."""

from __future__ import annotations

from typing import Any

from hevi.talkcraft.oprim.contracts import TalkcraftRequest
from hevi.talkcraft.oskill.compiler import choose_motion_cards


def compile_talkcraft_plan(request: TalkcraftRequest) -> dict[str, Any]:
    errors = request.validate()
    cards = choose_motion_cards(
        [{"cue_id": cue.cue_id, "start_s": cue.start_s, "end_s": cue.end_s} for cue in request.cues],
        card_limit=request.card_limit,
    )
    unique_categories = len({str(card["category"]) for card in cards})
    anti_slideshow = {
        "enabled": request.anti_slideshow,
        "unique_card_categories": unique_categories,
        "halt": request.anti_slideshow and len(cards) >= 3 and unique_categories < 2,
        "rule": "do not reuse a still-card pattern across the whole voice track",
    }
    if anti_slideshow["halt"]:
        errors.append("motion variety is too low for anti-slideshow policy")
    return {
        "status": "blocked" if errors else "planned",
        "request": request.to_dict(),
        "cards": cards,
        "anti_slideshow": anti_slideshow,
        "render_handoff": "Remotion/HEVI timeline renderer",
        "errors": errors,
    }


__all__ = ["compile_talkcraft_plan"]
