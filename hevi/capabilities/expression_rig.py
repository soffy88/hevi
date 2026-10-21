"""``image.expression_rig`` / ``image.expression_contact_sheet`` capabilities.

Registry wrappers around the hand-drawn character expression rig
(:mod:`hevi.layer4_legacy.handdraw.expression_rig`): a character is defined
once as a model sheet, and expressions are rendered by combining parts --
``(view, emotion)`` presets with optional per-part overrides for eyes,
mouth, brows and extras.  The shipped demo character is an original
design; see ``docs/rules/expression_rig.md`` for the naming/combination
rules and the originality red line.

CPU-only, no paid calls, deterministic from the render ``seed``.  Fails
closed with ``CapabilityError`` on any invalid input instead of returning
a fabricated success.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityError,
    CapabilityResult,
    register,
)

logger = logging.getLogger(__name__)

_Registered = False


def _enums() -> dict[str, list[str]]:
    from hevi.layer4_legacy.handdraw.expression_rig import (
        BROW_STYLES,
        CHARACTERS,
        EMOTIONS,
        EXTRA_STYLES,
        EYE_STYLES,
        MOUTH_STYLES,
        VIEWS,
    )

    return {
        "characters": sorted(CHARACTERS),
        "views": list(VIEWS),
        "emotions": sorted(EMOTIONS),
        "eyes": list(EYE_STYLES),
        "mouths": list(MOUTH_STYLES),
        "brows": list(BROW_STYLES),
        "extras": list(EXTRA_STYLES),
    }


def _face_params_schema() -> dict[str, Any]:
    e = _enums()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "character": {"type": "string", "enum": e["characters"], "default": "tuantuan"},
            "view": {"type": "string", "enum": e["views"], "default": "front"},
            "emotion": {"type": "string", "enum": e["emotions"], "default": "neutral"},
            "eyes": {"type": "string", "enum": e["eyes"]},
            "mouth": {"type": "string", "enum": e["mouths"]},
            "brows": {"type": "string", "enum": e["brows"]},
            "extras": {
                "type": "array",
                "items": {"type": "string", "enum": e["extras"]},
                "uniqueItems": True,
            },
            "size": {"type": "integer", "minimum": 96, "maximum": 1024, "default": 480},
        },
    }


def _sheet_params_schema() -> dict[str, Any]:
    e = _enums()
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "character": {"type": "string", "enum": e["characters"], "default": "tuantuan"},
            "views": {
                "type": "array",
                "items": {"type": "string", "enum": e["views"]},
                "minItems": 1,
                "uniqueItems": True,
            },
            "emotions": {
                "type": "array",
                "items": {"type": "string", "enum": e["emotions"]},
                "minItems": 1,
                "uniqueItems": True,
            },
            "cell": {"type": "integer", "minimum": 96, "maximum": 512, "default": 220},
        },
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_expression_rig(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.layer4_legacy.handdraw.expression_rig import (
        get_character,
        render_face,
        resolve_face,
    )

    params = params or {}
    try:
        face = resolve_face(
            character=params.get("character", "tuantuan"),
            view=params.get("view", "front"),
            emotion=params.get("emotion", "neutral"),
            eyes=params.get("eyes"),
            mouth=params.get("mouth"),
            brows=params.get("brows"),
            extras=params.get("extras"),
        )
        image = render_face(
            character=face.character,
            view=face.view,
            emotion=face.emotion,
            eyes=params.get("eyes"),
            mouth=params.get("mouth"),
            brows=params.get("brows"),
            extras=params.get("extras"),
            seed=int(seed),
            size=int(params.get("size", 480)),
        )
    except (ValueError, TypeError) as exc:
        raise CapabilityError(f"image.expression_rig: {exc}") from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "expression.png"
    image.save(png_path)
    sidecar = out_dir / "expression.json"
    sidecar.write_text(
        json.dumps(
            {
                "resolved": face.to_dict(),
                "seed": int(seed),
                "model_sheet": get_character(face.character).model_sheet(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not png_path.is_file():
        raise CapabilityError("image.expression_rig: render incomplete")
    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=_sha256_file(png_path),
        qa={
            "sidecar": str(sidecar),
            "resolved": face.to_dict(),
            "seed": int(seed),
        },
    )


def _render_contact_sheet(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.layer4_legacy.handdraw.expression_rig import build_contact_sheet

    params = params or {}
    try:
        sheet = build_contact_sheet(
            character=params.get("character", "tuantuan"),
            views=params.get("views"),
            emotions=params.get("emotions"),
            cell=int(params.get("cell", 220)),
            seed=int(seed),
        )
    except (ValueError, TypeError) as exc:
        raise CapabilityError(f"image.expression_contact_sheet: {exc}") from exc

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "expression_contact_sheet.png"
    sheet.save(png_path)
    sidecar = out_dir / "expression_contact_sheet.json"
    sidecar.write_text(
        json.dumps(
            {
                "character": params.get("character", "tuantuan"),
                "views": params.get("views"),
                "emotions": params.get("emotions"),
                "cell": int(params.get("cell", 220)),
                "seed": int(seed),
                "sheet_size": list(sheet.size),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if not png_path.is_file():
        raise CapabilityError("image.expression_contact_sheet: render incomplete")
    return CapabilityResult(
        png=str(png_path),
        duration_s=0.0,
        sha256=_sha256_file(png_path),
        qa={
            "sidecar": str(sidecar),
            "sheet_size": list(sheet.size),
            "seed": int(seed),
        },
    )


def register_expression_rig_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.expression_rig",
            kind="shot",
            aspects=["1:1", "16:9", "9:16"],
            params_schema=_face_params_schema(),
            cpu_cost_hint=0.2,
            render=_render_expression_rig,
            description=(
                "Hand-drawn character expression rig: renders one expression "
                "of an original demo character by combining parts "
                "(view x emotion preset, with optional eyes/mouth/brows/"
                "extras overrides), procedurally with rough hand-drawn "
                "strokes. Deterministic from the render seed; writes a "
                "transparent PNG plus a JSON sidecar with the resolved "
                "parts and the character model sheet."
            ),
            line="handdraw",
        )
    )
    register(
        Capability(
            name="image.expression_contact_sheet",
            kind="shot",
            aspects=["16:9", "1:1"],
            params_schema=_sheet_params_schema(),
            cpu_cost_hint=0.5,
            render=_render_contact_sheet,
            description=(
                "Expression-rig proof sheet: a labelled grid (rows = views, "
                "columns = emotions) for checking that expressions are "
                "distinguishable and the character stays on-model."
            ),
            line="handdraw",
        )
    )
    logger.info("registered expression rig capabilities")
    return ["image.expression_rig", "image.expression_contact_sheet"]
