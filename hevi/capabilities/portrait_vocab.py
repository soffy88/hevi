"""Portrait prompt vocabulary capability.

Registers one ``hevi.capabilities`` entry:

* ``image.portrait_vocab`` — the portrait-performance prompt library
  in ``hevi.image.portrait_vocab`` (66 bilingual entries in 8
  categories: video micro-actions, posture, hair/head, hands & held
  objects, motion, sitting, standing, gaze).  Three actions:

  - ``list`` / ``search``: browse the catalogue (by category and/or
    free-text query); writes ``portrait_vocab_catalogue.json``.
  - ``assemble``: pick at most one entry per category (one string
    parameter per category: an entry id, Chinese name or English
    phrase) and get a bilingual prompt back -- a Chinese narrative
    expanded from each pick's concrete ``how`` text (person first,
    scene second) plus the English phrase string.  With
    ``mode="motion"`` the artifact also carries a ``motion_prompt``
    (video micro-action first) ready for a PixStag shot package.
    Conflicting picks (e.g. eyes closed x looking at the camera,
    sitting x standing) are rejected unless ``on_conflict="warn"``.

  Fully local: no keys, no network, zero cost -- this capability only
  assembles text; rendering stays with ``image.gpt_generate`` /
  ``image.gpt_edit`` / the PixStag line.

Data provenance: verbatim transcription of the image pages Soffy
forwarded on 2026-10-23 (archive
``~/workspace/references/portrait-prompt-vocab/VOCAB.md``).  The source
has no expression category; none is invented.

Registration note: this module registers itself on import (guarded,
idempotent), following the ``shot.recipe_cards`` / ``image.brush_scene``
precedent.  ``hevi/capabilities/__init__.py`` is intentionally NOT
edited here because that file carries unrelated uncommitted work;
once that lands, move the import there and drop the import-time call.
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

_CATEGORY_PARAMS = (
    "video_micro",
    "posture",
    "hair_head",
    "hands",
    "motion",
    "sitting",
    "standing",
    "gaze",
)


def _vocab():
    from hevi.image import portrait_vocab

    return portrait_vocab


def _render_portrait_vocab(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    pv = _vocab()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action", "list"))
    try:
        if action in ("list", "search"):
            items = pv.search(
                str(params.get("category", "")),
                query=str(params.get("query", "")),
                limit=int(params.get("limit", 200)),
            )
            payload = {
                "source": pv.load_index()["source"],
                "version": pv.load_index()["version"],
                "counts": pv.counts(),
                "total": pv.load_index()["total"],
                "phrasing": {
                    "doc": "hevi/image/portrait_vocab/PHRASING.md",
                    "rules": pv.phrasing_rules(),
                    "note": (
                        "Writing standard distilled from this vocabulary: "
                        "read the doc before hand-writing portrait prompts; "
                        "assemble() output (detail_zh) follows it."
                    ),
                },
                "returned": len(items),
                "filters": {
                    "action": action,
                    "category": str(params.get("category", "")),
                    "query": str(params.get("query", "")),
                },
                "entries": items,
            }
            path = out_dir / "portrait_vocab_catalogue.json"
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
                        "Portrait performance vocabulary (66 entries, 8 "
                        "categories). Pick at most one entry per category, "
                        "then call again with action=assemble."
                    ),
                },
            )
        if action == "assemble":
            selection = {
                cat: params[cat]
                for cat in _CATEGORY_PARAMS
                if params.get(cat)
            }
            assembled = pv.assemble(
                selection,
                mode=str(params.get("mode", "image")),
                identity=params.get("identity") or None,
                subject=params.get("subject") or None,
                scene=params.get("scene") or None,
                framing=params.get("framing") or None,
                on_conflict=str(params.get("on_conflict", "error")),
            )
            payload = {
                "mode": assembled["mode"],
                "selection": selection,
                "entry_ids": [e["id"] for e in assembled["entries"]],
                "entries": assembled["entries"],
                "detail_zh": assembled["detail_zh"],
                "prompt_zh": assembled["prompt_zh"],
                "prompt_en": assembled["prompt_en"],
                "motion_prompt": assembled["motion_prompt"],
                "conflicts": assembled["conflicts"],
                "warnings": assembled["warnings"],
                "phrasing": {
                    "doc": "hevi/image/portrait_vocab/PHRASING.md",
                    "rules": pv.phrasing_rules(),
                },
            }
            path = out_dir / "portrait_prompt.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return CapabilityResult(
                sha256=compute_sha256(path),
                qa={
                    "prompt_json": str(path),
                    "mode": payload["mode"],
                    "entry_ids": payload["entry_ids"],
                    "prompt_zh": payload["prompt_zh"],
                    "prompt_en": payload["prompt_en"],
                    "motion_prompt": payload["motion_prompt"],
                    "warnings": payload["warnings"],
                    "phrasing_rules": [
                        r["title"] for r in payload["phrasing"]["rules"]
                    ],
                    "phrasing_doc": payload["phrasing"]["doc"],
                    "note": (
                        "Assembled locally at zero cost; feed prompt_zh / "
                        "prompt_en to an image backend, or motion_prompt "
                        "to a PixStag shot package. detail_zh doubles as "
                        "worked examples of the phrasing spec "
                        "(hevi/image/portrait_vocab/PHRASING.md)."
                    ),
                },
            )
        raise CapabilityError(
            f"image.portrait_vocab: unknown action {action!r} "
            "(want list|search|assemble)"
        )
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"image.portrait_vocab: {exc}") from exc


def register_portrait_vocab_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    category_props = {
        cat: {
            "type": "string",
            "description": (
                f"One {cat} entry: id, Chinese name or English phrase "
                "(at most one per category)"
            ),
        }
        for cat in _CATEGORY_PARAMS
    }
    register(
        Capability(
            name="image.portrait_vocab",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "search", "assemble"],
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
                    "mode": {
                        "type": "string",
                        "enum": ["image", "motion"],
                        "default": "image",
                        "description": "assemble: motion also emits a PixStag-ready motion_prompt (video_micro first)",
                    },
                    **category_props,
                    "identity": {
                        "type": "string",
                        "description": "assemble: identity sentence first, e.g. 脸型五官按参考图",
                    },
                    "subject": {
                        "type": "string",
                        "description": "assemble: subject/outfit sentence, after identity",
                    },
                    "scene": {
                        "type": "string",
                        "description": "assemble: scene sentence, after the person (person first, scene second)",
                    },
                    "framing": {
                        "type": "string",
                        "description": "assemble: framing line last, e.g. 拍到腰部，双手和支撑肘入画，写实皮肤，16:9",
                    },
                    "on_conflict": {
                        "type": "string",
                        "enum": ["error", "warn"],
                        "default": "error",
                        "description": "assemble: conflicting picks are errors, or warnings when 'warn'",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_portrait_vocab,
            description=(
                "Portrait performance prompt vocabulary (66 bilingual "
                "entries, 8 categories: video micro-actions, posture, "
                "hair/head, hands & held objects, motion, sitting, "
                "standing, gaze). list/search the catalogue, or assemble "
                "a bilingual portrait prompt from at most one pick per "
                "category -- Chinese narrative expanded from each "
                "pick's concrete 'how' text, person before scene, "
                "conflicts rejected; motion mode emits a PixStag-ready "
                "motion_prompt. Zero cost, offline, text only."
            ),
            line="image",
        )
    )
    return ["image.portrait_vocab"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_portrait_vocab_capabilities_once()
