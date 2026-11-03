"""Shot recipe card capability (video-shotcraft import).

Registers one ``hevi.capabilities`` entry (precedent:
``image.handraw_styles`` -- a catalogue capability over an imported,
attribution-carrying data library):

* ``shot.recipe_cards`` — catalogue / search / fetch of the 124 shot
  recipe cards imported from Vincentwei1021/video-shotcraft
  (Apache-2.0) into ``hevi/creative/shotlang/shotcraft_data/``.
  With ``name`` it returns that card's full Markdown; without, a
  filtered catalogue.  Data-only: rendering a card's motion still
  happens in the upstream Remotion demos / the caller's own pipeline.

Registration note: this module registers itself on import (guarded,
idempotent).  ``hevi/capabilities/__init__.py`` is intentionally NOT
edited by the importing change because that file carries unrelated
uncommitted work; once that lands, move the import there next to
handraw_styles and drop the import-time call.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _lib():
    from hevi.creative.shotlang import shotcraft

    return shotcraft


def _render_recipe_cards(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    lib = _lib()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = str(params.get("name", "") or "")
    try:
        index = lib.load_index()
        if name:
            card = lib.get_card(name)
            cards = [card]
            md_path = out_dir / f"{name}.md"
            md_path.write_text(card["markdown"], encoding="utf-8")
        else:
            cards = lib.list_cards(
                category=str(params.get("category", "")),
                query=str(params.get("query", "")),
                energy=str(params.get("energy", "")),
                limit=int(params.get("limit", 500)),
            )
            md_path = None
    except KeyError as exc:
        raise CapabilityError(f"shot.recipe_cards: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"shot.recipe_cards: {exc}") from exc

    payload = {
        "source": index["source"],
        "license": index["license"],
        "attribution": index["attribution"],
        "upstream_commit": index["upstream_commit"],
        "counts": index["counts"],
        "returned": len(cards),
        "filters": {
            "name": name,
            "category": str(params.get("category", "")),
            "query": str(params.get("query", "")),
            "energy": str(params.get("energy", "")),
        },
        "cards": cards,
    }
    catalogue_path = out_dir / "shotcraft_catalogue.json"
    catalogue_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        sha256=compute_sha256(catalogue_path),
        qa={
            "catalogue_json": str(catalogue_path),
            "card_markdown": str(md_path) if md_path else None,
            "counts": index["counts"],
            "returned": len(cards),
            "note": (
                "124 shot recipe cards in 10 functional categories "
                "(camera/data/effects/interaction/opening/outro/rhythm/"
                "transition/typography/ui-entrance). Fetch one card by "
                "name for its full recipe (意图/动效核心/参数表/已知坑/"
                "参考实现); demo code stays in the upstream checkout."
            ),
        },
    )


def register_shotcraft_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="shot.recipe_cards",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "default": "",
                        "description": "Exact card name (e.g. crash-zoom-punch); returns the full card Markdown",
                    },
                    "category": {
                        "type": "string",
                        "default": "",
                        "description": "One of camera/data/effects/interaction/opening/outro/rhythm/transition/typography/ui-entrance",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "Free-text filter over name/one-liner/applies-to/tags",
                    },
                    "energy": {
                        "type": "string",
                        "default": "",
                        "description": "Energy substring filter (高/中/低)",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "default": 500,
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_recipe_cards,
            description=(
                "Catalogue of the video-shotcraft shot recipe cards "
                "(Vincentwei1021/video-shotcraft, Apache-2.0): 124 cards "
                "in 10 functional categories, each with intent, motion "
                "recipe, parameter table, pitfalls and an upstream demo "
                "pointer. Use to pick a shot by name/category/keyword "
                "before writing a ShotLangSpec or a Remotion shot."
            ),
            line="shotlang",
        )
    )
    return ["shot.recipe_cards"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_shotcraft_capabilities_once()
