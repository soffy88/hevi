"""Semantic color palette table for Particle Science animation (幼儿科普色彩)."""

from __future__ import annotations

SEMANTIC_PALETTES = {
    "water": {
        "primary": "#3b82f6",
        "secondary": "#93c5fd",
        "glow": "#60a5fa",
        "bg": "#eff6ff",
        "name": "水之蓝"
    },
    "heat": {
        "primary": "#f97316",
        "secondary": "#fdba74",
        "glow": "#fb923c",
        "bg": "#fff7ed",
        "name": "热之橙"
    },
    "life": {
        "primary": "#22c55e",
        "secondary": "#86efac",
        "glow": "#4ade80",
        "bg": "#f0fdf4",
        "name": "生命绿"
    },
    "energy": {
        "primary": "#eab308",
        "secondary": "#fef08a",
        "glow": "#facc15",
        "bg": "#fefce8",
        "name": "能量金"
    },
    "sky": {
        "primary": "#0ea5e9",
        "secondary": "#bae6fd",
        "glow": "#38bdf8",
        "bg": "#f0f9ff",
        "name": "天空蓝"
    }
}


def get_palette(theme: str) -> dict[str, str]:
    return SEMANTIC_PALETTES.get(theme, SEMANTIC_PALETTES["sky"])


__all__ = ["SEMANTIC_PALETTES", "get_palette"]
