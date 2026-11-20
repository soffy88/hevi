"""ComfyUI gallery node contract schema (``video.pose_comfyui_gallery_node_schema``).

Contract-only schema for one pose-gallery ComfyUI node
call: its id, the node class, the depth switch, and the
inputs. The four node classes are the ones verified in the
upstream ``nodes.py`` (PoseGalleryNode, CostumeGalleryNode,
PortraitGalleryNode, CharacterRecipeNode); the plugin reuses
ComfyUI's own torch/numpy/Pillow/aiohttp and adds no extra
dependency. Clean-room restatement of the method (see
``AI_POSE_GALLERY_ZH_ATTRIBUTION.md``); no upstream code
appears in this schema.

This module is a **contract layer only**. The schema never
renders, scores, or calls a model; ``compile`` returns a
contract declaring ``executed_here: false`` and
``output_file: None`` on a well-formed node call, and raises
``CapabilityError`` on any shape violation. No ComfyUI
instance is contacted here.
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

NODE_CLASSES: frozenset[str] = frozenset(
    {
        "PoseGalleryNode",
        "CostumeGalleryNode",
        "PortraitGalleryNode",
        "CharacterRecipeNode",
    }
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "node_id": {"type": "string", "minLength": 1},
        "node": {"type": "string"},
        "use_depth": {"type": "boolean"},
        "depth_source": {"type": "string"},
        "inputs": {"type": "object"},
    },
    "required": ["node_id", "node", "use_depth"],
    "additionalProperties": False,
}


def compile_pose_comfyui_gallery_node(call: Any) -> dict[str, Any]:
    """Compile one ComfyUI gallery node call contract.

    Returns a contract declaring ``executed_here: false``
    and ``output_file: None`` on a well-formed call.
    Raises :class:`CapabilityError` on any shape violation.
    The contract certifies the shape of the call only; it
    contacts no ComfyUI instance.
    """
    if not isinstance(call, dict):
        raise CapabilityError("pose_comfyui_gallery_node: call must be a JSON object")
    for key in SCHEMA["required"]:
        if key not in call:
            raise CapabilityError(f"pose_comfyui_gallery_node: missing required field {key!r}")
    extra = sorted(set(call) - set(SCHEMA["properties"]))
    if extra:
        raise CapabilityError("pose_comfyui_gallery_node: unknown fields: " + ", ".join(extra))
    node = call["node"]
    if node not in NODE_CLASSES:
        raise CapabilityError(
            f"pose_comfyui_gallery_node: node must be one of {sorted(NODE_CLASSES)}, got {node!r}"
        )
    use_depth = call["use_depth"]
    if not isinstance(use_depth, bool):
        raise CapabilityError("pose_comfyui_gallery_node: use_depth must be a boolean")
    if node == "PoseGalleryNode" and use_depth is True and call.get("depth_source") != "img/depth":
        raise CapabilityError(
            "pose_comfyui_gallery_node: a PoseGalleryNode with "
            "use_depth true must declare depth_source img/depth"
        )
    inputs = call.get("inputs", {})
    if not isinstance(inputs, dict):
        raise CapabilityError("pose_comfyui_gallery_node: inputs must be an object when given")
    return {
        "contract": "pose-comfyui-gallery-node",
        "node_id": call["node_id"],
        "node": node,
        "use_depth": use_depth,
        "inputs": inputs,
        "executed_here": False,
        "output_file": None,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_pose_comfyui_gallery_node(params.get("node_call"))
    contract_path = out_dir / "pose_comfyui_gallery_node_contract.json"
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={
            "report_json": str(contract_path),
            "node_id": contract["node_id"],
            "executed_here": False,
        },
    )


def register_pose_comfyui_gallery_node_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.pose_comfyui_gallery_node_schema",
            kind="video",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "node_call": {"type": "object"},
                },
                "required": ["node_call"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            line="video",
            description=(
                "Pose-gallery ComfyUI node contract (fake): four "
                "verified node classes, depth switch with img/depth "
                "source, inputs object; shape only, never executed here."
            ),
        )
    )
    return ["video.pose_comfyui_gallery_node_schema"]


__all__ = [
    "NODE_CLASSES",
    "SCHEMA",
    "compile_pose_comfyui_gallery_node",
    "register_pose_comfyui_gallery_node_schema_capabilities_once",
]
