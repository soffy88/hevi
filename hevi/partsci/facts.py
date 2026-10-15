"""Fact cards, local knowledge base, and causal mechanism consistency check."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Local offline knowledge base with authoritative source URLs (no fabrication)
_LOCAL_KB: dict[str, dict[str, Any]] = {
    "sky_blue": {
        "concept": "为什么天是蓝的",
        "fact": "太阳光由七色光组成，蓝光波长较短，被大气层中的气体分子向四面八方散射，使天空呈现蓝色。",
        "mechanism": "太阳光散射",
        "source_url": "https://spaceplace.nasa.gov/blue-sky/en/",
        "license": "Public Domain (NASA Science)"
    },
    "rain_source": {
        "concept": "雨从哪里来",
        "fact": "地面上的水被太阳加热蒸发成水蒸气上升，在高空遇冷凝结成小水滴汇聚成云，水滴变重后降落形成雨。",
        "mechanism": "蒸发凝结循环",
        "source_url": "https://www.noaa.gov/education/resource-collections/weather-atmosphere-education/water-cycle",
        "license": "Public Domain (NOAA Education)"
    },
    "seed_grow": {
        "concept": "种子怎么长大",
        "fact": "种子吸收水分膨胀破壳，在土壤中依靠根系吸收养分、绿叶进行光合作用向上生长。",
        "mechanism": "吸水光合作用",
        "source_url": "https://www.britannica.com/science/germination",
        "license": "Educational Reference (Britannica)"
    }
}


def get_fact_card(concept_key: str) -> dict[str, Any]:
    card = _LOCAL_KB.get(concept_key)
    if not card:
        raise ValueError(f"Unknown concept key {concept_key!r} in local knowledge base (offline mode: no fabrication allowed).")
    return card


def verify_mechanism(concept_key: str, script_mechanism: str) -> bool:
    """Mechanism anti-error check: script causal mechanism must match fact card."""
    card = get_fact_card(concept_key)
    expected = card.get("mechanism", "")
    return expected in script_mechanism or script_mechanism in expected


__all__ = ["_LOCAL_KB", "get_fact_card", "verify_mechanism"]
