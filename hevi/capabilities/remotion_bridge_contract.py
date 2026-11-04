"""Remotion bridge contract, fake layer (``video.remotion_bridge_contract``).

Contract-only bridge between a shotcraft card plan and a Remotion
render request. Given a plan naming a tuned card from the 124-card
index, a theme from the nine-preset vocabulary, a composition name,
and a frame grid, this module compiles the render request contract
and records, honestly, that no render happened here:
``executed_here`` is always false, ``rendered_here`` is always
false, and ``output_file`` is always null. Nothing is rendered,
no browser is launched, and no package is installed.

Measured block, recorded here rather than smoothed over: on
2026-11-04 a real Remotion render was attempted inside the
production container (``hevi-cftunnel-hevi-api-1``) with the
smoke manifest from ``video.remotion_bridge_smoke`` (MotionGraphics,
540x960 @ 30fps, 90 frames), writing only to an ephemeral
``/tmp`` probe directory that was removed afterwards. The render
never started: Remotion tried to download Chrome Headless Shell
into ``/app/hevi-remotion/node_modules/.remotion`` and failed
with ``EACCES: permission denied`` because that directory tree
is root-owned while the service runs as user ``hevi``. No MP4
was produced. Until the image or build gives the render user a
writable browser directory (or pre-bundles the browser), every
contract compiled here stays blocked-before-render. See
VIDEO_SHOTCRAFT_ATTRIBUTION.md.
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
from hevi.capabilities.shotcraft_card_index import list_shotcraft_cards
from hevi.capabilities.shotcraft_theme_vocabulary import (
    PALETTE_PRECEDENCE,
    THEME_PRESETS,
)

_Registered = False

# The measured block, kept as data so callers cannot mistake this
# contract for a verified render.
RENDER_BLOCK = {
    "measured": "2026-11-04",
    "container": "hevi-cftunnel-hevi-api-1",
    "composition": "MotionGraphics",
    "width": 540,
    "height": 960,
    "fps": 30,
    "duration_frames": 90,
    "outcome": "blocked_before_render",
    "error": "EACCES: permission denied, mkdir "
    "'/app/hevi-remotion/node_modules/.remotion'",
    "error_stage": "browser download (Chrome Headless Shell) "
    "before any frame was rendered",
    "mp4_produced": False,
    "fix_required": "writable browser directory for the render "
    "user, or a pre-bundled browser, in the image/build; "
    "not a contract change",
}

# Ink Press keeps its issued look and cannot be recoloured; the
# same rule as the theme vocabulary gate.
_INK_PRESS = "Ink Press"


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_grid(grid: Any) -> dict[str, int]:
    if not isinstance(grid, dict):
        _fail("remotion bridge plan must declare a grid object")
    width = grid.get("width")
    height = grid.get("height")
    fps = grid.get("fps")
    frames = grid.get("frames")
    for name, value in (
        ("width", width),
        ("height", height),
        ("fps", fps),
        ("frames", frames),
    ):
        if not _is_int(value) or value <= 0:
            _fail(f"grid {name} must be a positive integer")
    return {"width": width, "height": height, "fps": fps, "frames": frames}


def compile_remotion_bridge_contract(plan: Any) -> dict[str, Any]:
    """Compile a Remotion render-request contract from a plan.

    Raises :class:`CapabilityError` on a malformed plan. The
    returned contract always carries ``executed_here: false``,
    ``rendered_here: false``, and ``output_file: null``: the
    render itself is blocked (see ``RENDER_BLOCK``) and is a
    separate case.
    """
    if not isinstance(plan, dict):
        _fail("remotion bridge plan must be a JSON object")
    card = plan.get("card")
    if not isinstance(card, str) or not card.strip():
        _fail("remotion bridge plan must name a shotcraft card")
    known_cards = {entry["name"] for entry in list_shotcraft_cards()}
    if card not in known_cards:
        _fail(
            f"card {card!r} is not one of the 124 tuned shotcraft "
            "cards; the synthesized 152-name catalogue does not count"
        )
    theme = plan.get("theme")
    if theme not in THEME_PRESETS:
        _fail(f"theme must be one of the nine presets: {list(THEME_PRESETS)}")
    if theme == _INK_PRESS and plan.get("palette_override"):
        _fail("Ink Press cannot be recoloured: palette_override is refused")
    composition = plan.get("composition")
    if not isinstance(composition, str) or not composition.strip():
        _fail("remotion bridge plan must name a composition")
    grid = _check_grid(plan.get("grid"))
    shots: list[dict[str, Any]] = []
    raw_shots = plan.get("shots", [])
    if not isinstance(raw_shots, list):
        _fail("shots must be a list")
    for index, shot in enumerate(raw_shots):
        if not isinstance(shot, dict):
            _fail(f"shots[{index}] must be an object")
        shot_card = shot.get("card")
        if shot_card not in known_cards:
            _fail(f"shots[{index}] card {shot_card!r} is not a tuned card")
        start = shot.get("start_frame")
        end = shot.get("end_frame")
        if not _is_int(start) or not _is_int(end) or start < 0 or end <= start:
            _fail(f"shots[{index}] needs 0 <= start_frame < end_frame")
        shots.append(
            {"card": shot_card, "start_frame": start, "end_frame": end}
        )
    return {
        "card": card,
        "theme": theme,
        "composition": composition,
        "grid": grid,
        "shots": shots,
        "palette_precedence": list(PALETTE_PRECEDENCE),
        "verification": dict(RENDER_BLOCK),
        "executed_here": False,
        "rendered_here": False,
        "output_file": None,
        "render_required": "separate case; container browser-dir "
        "permission must be fixed in the image/build first",
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    contract = compile_remotion_bridge_contract(params.get("plan"))
    contract_path = out_dir / "remotion_bridge_contract.json"
    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(contract_path),
        qa={"contract_json": str(contract_path), "executed_here": False,
            "rendered_here": False},
    )


def register_remotion_bridge_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.remotion_bridge_contract",
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
                "Remotion bridge contract (contract only): a tuned "
                "card, theme, composition, and grid compiled into a "
                "render request; rendering is blocked by the "
                "measured container EACCES and nothing is rendered here."
            ),
        )
    )
    return ["video.remotion_bridge_contract"]


__all__ = [
    "RENDER_BLOCK",
    "compile_remotion_bridge_contract",
    "register_remotion_bridge_contract_capabilities_once",
]
