"""Lottie overlay adapter, fake layer (``video.lottie_overlay_adapter``).

Contract-only adapter. Given an overlay plan it compiles the
contract for a Lottie vector-animation overlay: each overlay
names a Lottie JSON source by reference, declares its frame
bounds, its loop behaviour, and transparency (an overlay that
does not declare transparency fails). This module executes
nothing: ``executed_here`` is always false, ``rendered_here``
is always false, and ``output_file`` is always null. The web
player (``lottie-web``) is a method reference only; no player
is bundled, installed, probed, or invoked here, and no Lottie
JSON is read or copied. Hevi previously mentioned Lottie only
in a webrender sample; this is the first registered contract
for it, and it records honestly that nothing is rendered.
Real overlay rendering is a separate case. See
OPEN_SKILLS_ATTRIBUTION.md.
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

# Method reference only: the web player is named, never bundled.
PLAYER_NAME = "lottie-web"
PLAYER_ROLE = "web player, method reference only; no player bundled here"


def _fail(message: str) -> None:
    raise CapabilityError(message)


def compile_lottie_overlay_contract(plan: Any) -> dict[str, Any]:
    """Compile an overlay contract from an overlay plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``: nothing
    is overlaid here.
    """
    if not isinstance(plan, dict):
        _fail("overlay plan must be a JSON object")
    fps = plan.get("fps")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps <= 0:
        _fail("overlay plan must declare a positive fps")
    for field in ("width", "height"):
        value = plan.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            _fail(f"overlay plan must declare a positive integer {field}")
    overlays = plan.get("overlays")
    if not isinstance(overlays, list) or not overlays:
        _fail("overlay plan must declare a non-empty overlays list")
    compiled: list[dict[str, Any]] = []
    for index, overlay in enumerate(overlays):
        if not isinstance(overlay, dict):
            _fail(f"overlays[{index}] must be an object")
        overlay_id = overlay.get("id")
        if not isinstance(overlay_id, str) or not overlay_id:
            _fail(f"overlays[{index}] must declare an id")
        if overlay.get("source_kind") != "lottie_json":
            _fail(
                f"overlays[{index}] must declare source_kind 'lottie_json'"
            )
        source_ref = overlay.get("source_ref")
        if not isinstance(source_ref, str) or not source_ref:
            _fail(f"overlays[{index}] must name a source_ref")
        start = overlay.get("start_frame")
        end = overlay.get("end_frame")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
        ):
            _fail(
                f"overlays[{index}] must declare integer frame bounds "
                "with 0 <= start_frame < end_frame"
            )
        loop = overlay.get("loop")
        if not isinstance(loop, bool):
            _fail(f"overlays[{index}] must declare loop as a boolean")
        if overlay.get("transparent") is not True:
            _fail(
                f"overlays[{index}] must declare transparent true: "
                "an overlay without transparency is not an overlay"
            )
        compiled.append(
            {
                "index": index,
                "id": overlay_id,
                "source_kind": "lottie_json",
                "source_ref": source_ref,
                "start_frame": start,
                "end_frame": end,
                "loop": loop,
                "transparent": True,
                "layer": "lottie_overlay",
            }
        )
    return {
        "contract": "lottie_overlay",
        "fps": fps,
        "width": plan["width"],
        "height": plan["height"],
        "player": {
            "name": PLAYER_NAME,
            "role": PLAYER_ROLE,
            "bundled_here": False,
        },
        "overlays": compiled,
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_lottie_overlay_contract(params.get("plan"))
    contract_path = out_dir / "lottie_overlay_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False},
    )


def register_lottie_overlay_adapter_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.lottie_overlay_adapter",
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
                "Lottie overlay adapter, fake layer: compiles an "
                "overlay contract (source by reference, frame bounds, "
                "loop, declared transparency); nothing is rendered "
                "here and no player is bundled."
            ),
        )
    )
    return ["video.lottie_overlay_adapter"]


__all__ = [
    "PLAYER_NAME",
    "compile_lottie_overlay_contract",
    "register_lottie_overlay_adapter_capabilities_once",
]
