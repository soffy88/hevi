"""Handraw-style numbered prompt library capabilities.

Registers two ``hevi.capabilities`` entries so every product line can use
the yang0/handraw-style numbered prompt library (365 visual styles,
167 layouts, 36 theme colors) by dotted name (CAPABILITY_CONTRACT.md;
precedents: ``video.hyperframes_styles``, ``image.gpt_generate``):

* ``image.handraw_styles`` — the library catalogue.  List/filter styles,
  layouts, theme colors and tones by category or keyword; the JSON
  artifact is regenerated from hevi's extracted index on every render.
* ``image.styled_generate`` — style number + theme -> a generated image.
  The prompt is assembled by ``hevi.image.handraw_style`` following the
  upstream rules (gpt-image-2 activation policy: style name, +core
  traits, or +numbered reference image), then rendered through the
  existing Monid GPT-Image backend (``image.gpt_generate`` /
  ``image.gpt_edit``).  The sidecar pins the ids used, the full
  bilingual prompts, the activation source, the cost and the upstream
  attribution.

Data: extracted index in ``hevi/image/handraw_data/`` (rebuild with its
``build_handraw_index.py``); reference images stay in the upstream
checkout (``HEVI_HANDRAW_HOME``, default ``~/projects/_refs/handraw-style``).

License: MIT License with Attribution Requirement -- free to use,
modify and commercialize; credit to author yang0 and
https://github.com/yang0/handraw-style must be retained (see
``hevi/image/handraw_data/ATTRIBUTION.md``).

Provider key: ``MONID_API_KEY`` (same as ``image.gpt_generate``); a
missing key surfaces as ``CapabilityError`` -- never a fake success.
"""

from __future__ import annotations

import asyncio
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

_COST_NOTE = (
    "Generation is billed per Monid endpoint rate against the workspace "
    "balance; the assembled prompt itself is free (local index)."
)


def _run_coro(coro):
    """Run an async service call from the synchronous capability render."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _handraw():
    from hevi.image import handraw_style

    return handraw_style


def _render_styles_catalogue(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    hs = _handraw()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    section = str(params.get("section", "all"))
    category = str(params.get("category", ""))
    query = str(params.get("query", ""))
    limit = int(params.get("limit", 2000))
    try:
        index = hs.load_index()
        sections: dict[str, list[dict[str, Any]]] = {}
        for name in ("styles", "layouts", "colors", "tones"):
            if section in ("all", name):
                sections[name] = hs.search(
                    name, category=category, query=query, limit=limit
                )
    except Exception as exc:
        raise CapabilityError(f"image.handraw_styles: {exc}") from exc

    catalogue_path = out_dir / "handraw_catalogue.json"
    payload = {
        "source": hs.HANDRAW_SOURCE_URL,
        "license": index["license"],
        "attribution": index["attribution"],
        "upstream_version": index["upstream_version"],
        "model_profile": index["model_profile"],
        "counts": index["counts"],
        "returned": {name: len(items) for name, items in sections.items()},
        "filters": {"section": section, "category": category, "query": query},
        **sections,
    }
    catalogue_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        sha256=compute_sha256(catalogue_path),
        qa={
            "catalogue_json": str(catalogue_path),
            "counts": index["counts"],
            "returned": payload["returned"],
            "note": (
                "Numbered prompt library (styles FA-FI / legacy 001-365, "
                "layouts, C-01..C-36 colors). Pick an id here, then call "
                "image.styled_generate with it."
            ),
        },
    )


def _render_styled_generate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    hs = _handraw()
    from hevi.audio.monid_client import MonidError
    from hevi.image import gpt_image_service

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        assembled = hs.assemble_prompt(
            str(params["style_id"]),
            str(params["theme"]),
            layout_id=params.get("layout_id") or None,
            color_id=params.get("color_id") or None,
            mode=str(params.get("mode", "pure")),
        )
    except Exception as exc:
        raise CapabilityError(f"image.styled_generate: {exc}") from exc

    style = assembled["style"]
    reference_path = None
    reference_attached = False
    reference_missing = False
    if assembled["use_reference_image"]:
        reference_path = hs.reference_image_path(style)
        reference_attached = reference_path is not None
        reference_missing = not reference_attached

    lang = str(params.get("prompt_lang", "zh"))
    prompt = hs.generation_prompt(
        assembled, lang=lang, reference_attached=reference_attached
    )
    size = str(params.get("size", "1024x1024"))
    quality = str(params.get("quality", "medium"))
    png_path = out_dir / "image.png"
    try:
        if reference_attached:
            result = _run_coro(
                gpt_image_service.gpt_image_edit(
                    image_paths=[reference_path],
                    prompt=prompt,
                    output_path=png_path,
                    size=size,
                    quality=quality,
                )
            )
        else:
            result = _run_coro(
                gpt_image_service.gpt_image_generate(
                    prompt=prompt,
                    output_path=png_path,
                    size=size,
                    quality=quality,
                )
            )
    except MonidError as exc:
        raise CapabilityError(f"image.styled_generate: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"image.styled_generate failed: {exc}") from exc

    cost = result.get("cost")
    sidecar = {
        "style_id": style["id"],
        "legacy_number": style["legacy_number"],
        "style_name": style["generation_name"],
        "reference": style["reference"],
        "group": style["group"],
        "layout_id": assembled["layout"]["id"] if assembled["layout"] else None,
        "color_id": assembled["color"]["id"] if assembled["color"] else None,
        "mode": assembled["mode"],
        "activation_source": assembled["activation_source"],
        "prompt_traits_included": bool(assembled["prompt_traits"]),
        "reference_image": {
            "required": assembled["use_reference_image"],
            "attached": reference_attached,
            "missing": reference_missing,
            "path": str(reference_path) if reference_path else None,
        },
        "prompt_lang": lang,
        "generation_prompt": prompt,
        "prompt_zh": assembled["prompt_zh"],
        "prompt_en": assembled["prompt_en"],
        "size": size,
        "quality": quality,
        "cost": cost,
        "attribution": hs.ATTRIBUTION,
        "source": hs.HANDRAW_SOURCE_URL,
    }
    sidecar_path = out_dir / "styled_sidecar.json"
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=compute_sha256(png_path),
        qa={
            "cost": cost,
            "style_id": style["id"],
            "activation_source": assembled["activation_source"],
            "reference_attached": reference_attached,
            "reference_missing": reference_missing,
            "sidecar_json": str(sidecar_path),
            "size": size,
            "quality": quality,
            "note": _COST_NOTE,
        },
    )


def register_handraw_style_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="image.handraw_styles",
            kind="shot",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["all", "styles", "layouts", "colors", "tones"],
                        "default": "all",
                    },
                    "category": {
                        "type": "string",
                        "default": "",
                        "description": "Style category prefix (FA..FI) or layout category",
                    },
                    "query": {
                        "type": "string",
                        "default": "",
                        "description": "Free-text filter over names/traits/keywords",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2000,
                        "default": 2000,
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_styles_catalogue,
            description=(
                "Catalogue of the handraw-style numbered prompt library "
                "(yang0/handraw-style, attribution required): 365 visual "
                "styles (FA-FI / legacy 001-365), 167 layouts, 36 theme "
                "colors, 16 tones. Use to pick a style/layout/color id "
                "before calling image.styled_generate."
            ),
            line="handraw_style",
        )
    )
    registered.append("image.handraw_styles")

    register(
        Capability(
            name="image.styled_generate",
            kind="shot",
            aspects=["9:16", "16:9", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "style_id": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Handraw style id (FI-001) or legacy number (333)",
                    },
                    "theme": {"type": "string", "minLength": 1},
                    "layout_id": {
                        "type": "string",
                        "description": "Optional layout id (SC-001); forces text mode except EC-*",
                    },
                    "color_id": {
                        "type": "string",
                        "description": "Optional theme color id (C-01..C-36) or color name",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["pure", "text"],
                        "default": "pure",
                        "description": "pure = upstream pure-image; text = graphic-text (theme verbatim + fixed suffix)",
                    },
                    "prompt_lang": {
                        "type": "string",
                        "enum": ["zh", "en"],
                        "default": "zh",
                        "description": "Which assembled prompt is sent to the backend; both are kept in the sidecar",
                    },
                    "size": {
                        "type": "string",
                        "default": "1024x1024",
                        "description": "WIDTHxHEIGHT, multiples of 16, aspect 1:3..3:1",
                    },
                    "quality": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "max"],
                        "default": "medium",
                    },
                },
                "required": ["style_id", "theme"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,  # cloud endpoint; local cost is upload + poll only
            render=_render_styled_generate,
            description=(
                "Generate an image in a numbered handraw-style visual style: "
                "style_id + theme (+ optional layout_id/color_id) are assembled "
                "into a bilingual prompt by the library's gpt-image-2 activation "
                "rules and rendered via the Monid GPT-Image backend. Use for "
                "styled stills and covers where a named, reproducible look is "
                "wanted instead of a hand-written prompt."
            ),
            line="handraw_style",
        )
    )
    registered.append("image.styled_generate")

    return registered
