"""LivLiv character catalogue (from vendor/livliv-player/characters/index.json)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

def characters_enabled() -> bool:
    v = os.environ.get("LIVLIV_CHARACTERS_ENABLED", "true").strip().lower()
    return v not in ("0", "false", "no", "off")

VENDOR = Path("/data/soffy/vendor/livliv-player")
INDEX = VENDOR / "characters" / "index.json"

def list_characters() -> list[dict[str, Any]]:
    if INDEX.is_file():
        return json.loads(INDEX.read_text(encoding="utf-8"))
    # fallback minimal
    return [{"id": "d03ft", "name": "Nana"}]

def character_name(cid: str) -> str:
    for c in list_characters():
        if c["id"] == cid:
            return c.get("name", cid)
    return cid

def credit(cid: str) -> str:
    for c in list_characters():
        if c["id"] == cid:
            return c.get("credit", "Characters: LivLiv (livliv.ai)")
    return "Characters: LivLiv (livliv.ai)"

def package_path(cid: str) -> Path:
    return VENDOR / "characters" / f"{cid}.livliv"