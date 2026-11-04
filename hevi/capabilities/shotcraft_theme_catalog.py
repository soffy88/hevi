"""Shotcraft theme catalog schema (``video.shotcraft_theme_catalog``).

Contract-only catalog of the nine theme presets: schema plus
catalog data restated in hevi's own words. Each entry names the
preset, carries a one-line gloss derived from the preset name
only, records whether recolouring is locked, and declares the
palette fields of the schema. Palette *values* are deliberately
not asserted here: ``palette_values`` is always null, because no
palette value table from any outside repository was copied into
hevi. The palette precedence order (schema default, preset
default, project palette, explicit per-clip edit) is the same
order the theme vocabulary gate enforces, and Ink Press keeps
its issued look and cannot be recoloured. This module renders
nothing: ``executed_here`` is always false and ``output_file``
is always null. See VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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
from hevi.capabilities.shotcraft_theme_vocabulary import (
    PALETTE_PRECEDENCE,
    THEME_PRESETS,
)

_Registered = False

# Palette fields of the catalog schema. Field names only; no
# colour values are asserted for any preset.
PALETTE_FIELDS: tuple[str, ...] = (
    "background",
    "surface",
    "accent",
    "text",
)

# One-line glosses, derived from the preset display names only.
# No theme description text from any outside source is copied.
_THEME_GLOSSES: dict[str, str] = {
    "Ink Press": "ink-on-paper press look, kept as issued",
    "Modern Light": "bright, light presentation look",
    "Midnight": "dark night presentation look",
    "Sage": "muted green-grey calm look",
    "Coral": "warm coral-toned look",
    "Iris": "violet-toned look",
    "Deep Ocean": "deep blue water-toned look",
    "Obsidian Violet": "near-black violet look",
    "Vintage Kraft": "aged kraft-paper look",
}


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _entry(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "gloss": _THEME_GLOSSES[name],
        # Only Ink Press is recolour-locked; the other presets
        # follow the palette precedence order.
        "recolour_locked": name == "Ink Press",
        "palette_fields": list(PALETTE_FIELDS),
        "palette_values": None,
        "palette_values_asserted": False,
    }


def list_theme_catalog() -> list[dict[str, Any]]:
    """Return the nine-preset catalog (copies)."""
    return [_entry(name) for name in THEME_PRESETS]


def compile_theme_catalog(request: Any = None) -> dict[str, Any]:
    """Compile the theme catalog, optionally for one preset.

    ``request`` may be null (whole catalog) or an object with a
    ``theme`` name. An unknown theme raises
    :class:`CapabilityError`. Palette values are never asserted:
    every entry carries ``palette_values: null``.
    """
    if request is None:
        entries = list_theme_catalog()
    elif isinstance(request, dict):
        theme = request.get("theme")
        if theme is None:
            entries = list_theme_catalog()
        elif theme in THEME_PRESETS:
            entries = [_entry(theme)]
        else:
            _fail(
                f"theme must be one of the nine presets: "
                f"{list(THEME_PRESETS)}"
            )
    else:
        _fail("theme catalog request must be a JSON object or null")
    return {
        "preset_count": len(entries),
        "presets": entries,
        "palette_precedence": list(PALETTE_PRECEDENCE),
        "palette_values_asserted": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = compile_theme_catalog(params.get("request"))
    catalog_path = out_dir / "shotcraft_theme_catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(catalog_path),
        qa={"catalog_json": str(catalog_path), "executed_here": False},
    )


def register_shotcraft_theme_catalog_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.shotcraft_theme_catalog",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "request": {"type": ["object", "null"]},
                },
                "required": [],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Shotcraft theme catalog schema (contract only): "
                "the nine presets with name-derived glosses, "
                "recolour locks, and palette fields; no palette "
                "values are asserted and nothing is rendered here."
            ),
        )
    )
    return ["video.shotcraft_theme_catalog"]


__all__ = [
    "PALETTE_FIELDS",
    "compile_theme_catalog",
    "list_theme_catalog",
    "register_shotcraft_theme_catalog_capabilities_once",
]
