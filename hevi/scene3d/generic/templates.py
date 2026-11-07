"""oskill: scene templates.  A preset is just a scene JSON for the generic
interface; callers send ``{"template": name, ...overrides}`` and the overrides
are deep-merged (dicts merge, lists replace)."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
# legacy capability names -> generic templates
LEGACY_ALIASES = {"scene3d.planet_orbit": "planet_orbit", "scene3d.fox_wheat": "fox_wheat",
                  "scene3d.star_sea": "star_sea"}


def list_templates() -> list[str]:
    return sorted(p.stem for p in TEMPLATE_DIR.glob("*.json"))


def load_template(name: str) -> dict[str, Any]:
    name = LEGACY_ALIASES.get(name, name)
    p = TEMPLATE_DIR / f"{name}.json"
    if not p.is_file():
        raise ValueError(f"unknown scene template {name!r} (have {list_templates()})")
    return json.loads(p.read_text(encoding="utf-8"))


def deep_merge(base: Any, over: Any) -> Any:
    if isinstance(base, dict) and isinstance(over, dict):
        out = copy.deepcopy(base)
        for k, v in over.items():
            out[k] = deep_merge(base[k], v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(over)


def expand_template(doc: dict[str, Any]) -> dict[str, Any]:
    if "template" not in doc:
        return doc
    over = {k: v for k, v in doc.items() if k != "template"}
    base = load_template(str(doc["template"]))
    base.pop("template", None)
    return deep_merge(base, over)
