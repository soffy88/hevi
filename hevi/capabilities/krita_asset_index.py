"""Krita asset index, fake layer (``video.krita_asset_index``).

Contract-only adapter. Given a declared asset plan it
compiles a read-only index of layered painting assets: each
layer is named by reference with its kind, and animation
layers declare their frame counts. This module reads no
``.kra`` file, renders nothing, and edits nothing:
``executed_here`` is always false, ``rendered_here`` is
always false, and ``output_file`` is always null. The source
file is never modified; the index is a declaration record,
not a painting session. Krita itself is a desktop
application (GPL-3.0); no Krita code is copied here, no
brush bundle is packed, and no desktop application is
launched, installed, or probed. Real painting and export
are a separate real-machine case. See
FIFTEEN_TOOLS_ATTRIBUTION.md.
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

# Layer kinds this index recognizes, in our own vocabulary:
# paint layers, groups, animation layers, filter layers, and
# vector layers.
LAYER_KINDS = ("paint", "group", "animation", "filter", "vector")

# Export formats the index may record, by reference only.
EXPORT_FORMATS = ("png", "jpg", "webp")

MERGED_PREVIEW = "mergedimage.png"


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_krita_asset_index(plan: Any) -> dict[str, Any]:
    """Compile a read-only Krita asset index from a declared plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``: no
    file is read or written here.
    """
    if not isinstance(plan, dict):
        _fail("asset plan must be a JSON object")
    source_ref = plan.get("source_ref")
    if not isinstance(source_ref, str) or not source_ref:
        _fail("asset plan must name a .kra source_ref")
    if plan.get("source_preserved") is not True:
        _fail("asset plan must declare the .kra source preserved")
    if plan.get("mergedimage_png") is not True:
        _fail(
            "asset plan must declare the merged preview "
            f"({MERGED_PREVIEW}) present in the container"
        )
    if plan.get("read_actual_kra") is True:
        _fail("no .kra file is read here; the index is declarative only")
    if plan.get("brush_bundle_bundled") is True:
        _fail("no Krita brush bundle is packed into this repository")
    layers = plan.get("layers")
    if not isinstance(layers, list) or not layers:
        _fail("asset plan must declare a non-empty layers list")
    compiled_layers: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            _fail(f"layers[{index}] must be an object")
        layer_id = layer.get("id")
        if not isinstance(layer_id, str) or not layer_id:
            _fail(f"layers[{index}] must declare an id")
        layer_name = layer.get("name")
        if not isinstance(layer_name, str) or not layer_name:
            _fail(f"layers[{index}] must declare a name")
        kind = layer.get("kind")
        if kind not in LAYER_KINDS:
            _fail(
                f"layers[{index}] kind must be one of "
                + ", ".join(LAYER_KINDS)
            )
        entry: dict[str, Any] = {
            "index": index,
            "id": layer_id,
            "name": layer_name,
            "kind": kind,
        }
        if kind == "animation":
            frame_count = layer.get("frame_count")
            if (
                not isinstance(frame_count, int)
                or isinstance(frame_count, bool)
                or frame_count <= 0
            ):
                _fail(
                    f"layers[{index}] is an animation layer and must "
                    "declare a positive integer frame_count"
                )
            entry["frame_count"] = frame_count
        compiled_layers.append(entry)
    compiled_exports: list[dict[str, Any]] = []
    exports = plan.get("exports", [])
    if not isinstance(exports, list):
        _fail("asset plan exports must be a list")
    for index, export in enumerate(exports):
        if not isinstance(export, dict):
            _fail(f"exports[{index}] must be an object")
        export_id = export.get("id")
        if not isinstance(export_id, str) or not export_id:
            _fail(f"exports[{index}] must declare an id")
        export_format = export.get("format")
        if export_format not in EXPORT_FORMATS:
            _fail(
                f"exports[{index}] format must be one of "
                + ", ".join(EXPORT_FORMATS)
            )
        output_path = export.get("output_path")
        if not isinstance(output_path, str) or not output_path:
            _fail(f"exports[{index}] must declare an output_path")
        if output_path == source_ref:
            _fail(
                f"exports[{index}] output must be separate from the "
                ".kra source file"
            )
        compiled_exports.append(
            {
                "index": index,
                "id": export_id,
                "format": export_format,
                "output_path": output_path,
            }
        )
    return {
        "contract": "krita_asset_index",
        "source_ref": source_ref,
        "layers": compiled_layers,
        "exports": compiled_exports,
        "index_only": True,
        "kra_read_here": False,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "source_never_modified": True,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_krita_asset_index(params.get("plan"))
    contract_path = out_dir / "krita_asset_index.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_krita_asset_index_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.krita_asset_index",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Krita asset index, fake layer: compiles a "
                "read-only index of declared layers and exports "
                "for a .kra source; no file is read, rendered, "
                "or modified here."
            ),
        )
    )
    return ["video.krita_asset_index"]


__all__ = [
    "EXPORT_FORMATS",
    "LAYER_KINDS",
    "MERGED_PREVIEW",
    "compile_krita_asset_index",
    "register_krita_asset_index_capabilities_once",
]
