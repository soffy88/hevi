"""Eight-dimension portrait extension vocabulary capability.

Registers one ``hevi.capabilities`` entry:

* ``image.portrait_eight_dim_vocab`` -- the 32-entry extension
  vocabulary in ``hevi.image.portrait_vocab.eight_dim`` (fabric,
  skin/light, lens optics, micro-expression), restated in our own
  words from generic photographic language.  Two actions:

  - ``list`` / ``search``: browse the catalogue (by category
    and/or free-text query); writes
    ``portrait_eight_dim_catalogue.json``.
  - ``dimensions``: return the eight-dimension map (which
    dimensions take vocabulary picks and which take
    caller-supplied text).

Fully local: no keys, no network, zero cost -- this capability
only serves text; rendering stays with the image backends.  The
verbatim 66-entry ``portrait_vocab_index.json`` is untouched; this
extension follows the same entry shape.  Adult portraits only.
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

_CATEGORY_PARAMS = (
    "fabric",
    "skin_light",
    "lens_optics",
    "micro_expression",
)


def _vocab():  # type: ignore[no-untyped-def]
    from hevi.image.portrait_vocab import eight_dim

    return eight_dim


def _render_eight_dim_vocab(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    ed = _vocab()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action", "list"))
    try:
        if action in ("list", "search"):
            items = ed.search(
                str(params.get("category", "")),
                query=str(params.get("query", "")),
                limit=int(params.get("limit", 200)),
            )
            payload = {
                "source": ed.load_index()["source"],
                "version": ed.load_index()["version"],
                "counts": ed.counts(),
                "total": ed.load_index()["total"],
                "returned": len(items),
                "filters": {
                    "action": action,
                    "category": str(params.get("category", "")),
                    "query": str(params.get("query", "")),
                },
                "entries": items,
            }
            path = out_dir / "portrait_eight_dim_catalogue.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return CapabilityResult(
                sha256=compute_sha256(path),
                qa={
                    "catalogue_json": str(path),
                    "counts": payload["counts"],
                    "returned": len(items),
                    "note": (
                        "Eight-dimension extension vocabulary (32 "
                        "entries, 4 categories). Picks feed "
                        "image.portrait_eight_dim_assembler."
                    ),
                },
            )
        if action == "dimensions":
            payload = {
                "dimensions": list(ed.DIMENSIONS),
                "dimension_categories": dict(ed.DIMENSION_CATEGORIES),
                "note": (
                    "Dimensions without a category (anchoring, "
                    "environment, restraint, negatives) take "
                    "caller-supplied text judged by the qa.* gates."
                ),
            }
            path = out_dir / "portrait_eight_dim_dimensions.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return CapabilityResult(
                sha256=compute_sha256(path),
                qa={
                    "dimensions_json": str(path),
                    "dimensions": payload["dimensions"],
                },
            )
        raise CapabilityError(
            f"image.portrait_eight_dim_vocab: unknown action {action!r} "
            "(want list|search|dimensions)"
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"image.portrait_eight_dim_vocab: {exc}") from exc


_Registered = False


def register_portrait_eight_dim_vocab_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.portrait_eight_dim_vocab",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "search", "dimensions"],
                        "default": "list",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["", *_CATEGORY_PARAMS],
                        "default": "",
                        "description": "list/search: restrict to one category",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "list/search: free-text filter over zh/en/how/feeling",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 200,
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_eight_dim_vocab,
            description=(
                "Eight-dimension portrait extension vocabulary (32 "
                "bilingual entries, 4 categories: fabric, skin/light, "
                "lens optics, micro-expression). list/search the "
                "catalogue, or read the dimension map."
            ),
        )
    )
    return ["image.portrait_eight_dim_vocab"]


register_portrait_eight_dim_vocab_capabilities_once()
