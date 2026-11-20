"""Xiaoya wardrobe hot-swap gate (``qa.xiaoya_wardrobe_hotswap_gate``).

A wardrobe change swaps the host's whole look mid-stream
without stopping the broadcast: the branch under review keeps
a base avatar (``xiaoya_e``) and a short item list, each item
naming the avatar it maps to and the aliases that trigger it.
A change swaps the (idle, talk) clip pair together, crossfades
between clips so the cut is invisible (8 frames in the
measured run), and a restore item always returns the host to
the base avatar.

Clean-room restatement of the method found in the
``live-parity`` branch checkout (see
``DIGITAL_HOST_IMPROVEMENT_ATTRIBUTION.md``). This gate judges
the shape of a wardrobe declaration only; it never loads a
clip and never starts a stream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Avatar keys a wardrobe item may map to.
AVATAR_KEYS: frozenset[str] = frozenset({"xiaoya_d", "xiaoya_e", "v1"})

# The base avatar every restore returns to.
BASE_AVATAR = "xiaoya_e"

# Words that mark the restore item.
RESTORE_ALIASES: frozenset[str] = frozenset({"恢复", "复原", "默认"})

# Measured crossfade between clips.
MEASURED_CROSSFADE_FRAMES = 8


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_xiaoya_wardrobe_hotswap(wardrobe: Any) -> dict[str, Any]:
    """Validate a wardrobe hot-swap declaration.

    Verdicts are ``pass`` / ``fail`` only. The wardrobe fails
    when it is not an object, when its base avatar is not
    ``xiaoya_e``, when its item list is missing or an item
    lacks a name or maps to an unknown avatar, when no restore
    item returns to the base avatar, when a change does not
    swap the (idle, talk) pair together, when a change does
    not restore to base, or when no crossfade is declared.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(wardrobe, dict):
        return fail("wardrobe_not_object", "wardrobe must be a JSON object")
    if wardrobe.get("base_avatar") != BASE_AVATAR:
        return fail(
            "base_avatar_wrong",
            "the base avatar must be xiaoya_e",
        )
    items = wardrobe.get("items")
    if not isinstance(items, list) or not items:
        return fail("items_missing", "a non-empty wardrobe item list is required")
    restore_found = False
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            return fail("item_invalid", f"item {position} must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            return fail("item_invalid", f"item {position} needs a non-empty name")
        if item.get("avatar") not in AVATAR_KEYS:
            return fail(
                "item_invalid",
                f"item {position} must map to xiaoya_d, xiaoya_e or v1",
            )
        aliases = item.get("aliases") or []
        names = {name} | set(aliases if isinstance(aliases, list) else [])
        if names & RESTORE_ALIASES and item.get("avatar") == BASE_AVATAR:
            restore_found = True
    if not restore_found:
        return fail(
            "restore_missing",
            "a restore item returning to the base avatar is required",
        )
    switch = wardrobe.get("switch")
    if not isinstance(switch, dict):
        return fail("switch_missing", "a switch declaration is required")
    if switch.get("swaps_idle_talk_pair") is not True:
        return fail(
            "pair_swap_missing",
            "a wardrobe change must swap the (idle, talk) clip pair together",
        )
    if switch.get("restores_to_base") is not True:
        return fail(
            "restore_to_base_missing",
            "a change must be able to restore to the base avatar",
        )
    crossfade = switch.get("crossfade_frames")
    if not _is_int(crossfade) or crossfade < 1:
        return fail(
            "crossfade_missing",
            "a crossfade in frames must be declared (measured 8) so the cut is invisible",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_xiaoya_wardrobe_hotswap(params.get("wardrobe"))
    report_path = out_dir / "xiaoya_wardrobe_hotswap_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_xiaoya_wardrobe_hotswap_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.xiaoya_wardrobe_hotswap_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "wardrobe": {"type": "object"},
                },
                "required": ["wardrobe"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "xiaoya wardrobe hot-swap gate: base avatar xiaoya_e, "
                "named items, restore item present, (idle, talk) pair "
                "swapped together, crossfade declared."
            ),
        )
    )
    return ["qa.xiaoya_wardrobe_hotswap_gate"]


__all__ = [
    "AVATAR_KEYS",
    "BASE_AVATAR",
    "MEASURED_CROSSFADE_FRAMES",
    "RESTORE_ALIASES",
    "check_xiaoya_wardrobe_hotswap",
    "register_xiaoya_wardrobe_hotswap_gate_capabilities_once",
]
