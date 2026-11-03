"""Asset registry v2 (``story.asset_registry_v2``).

The drift problem in a multi-minute film is rarely one bad
picture. It is the same character stored twice, in two places,
under two names, with nobody able to say which copy is the
master. This registry fixes that with three layers and one rule:

1. Script layer: what the confirmed script says appears.
2. Asset layer: one master record per character, scene or prop.
   Episodes never store their own copy of an asset; they store
   a reference to the master.
3. Episode layer: which master assets this episode uses, and
   which shots are still waiting for material.

Rules enforced here:

- A name belongs to one asset. Registering a different asset
  under a name that is already taken fails; declare an alias
  for the same asset instead. A name that means two different
  things is two assets with different ids, never merged by
  string matching.
- A character master carries a face close-up plus front, side
  and back full views. A scene master carries a fixed skeleton
  (the spatial layout that must not move) plus its light.
- A derivative names its parent, what changed and what did not
  change. By default, an instant expression, a local close-up,
  a camera move, weather or damage does not get a derivative
  of its own; use the parent as-is, or declare the boundary
  explicitly. At most 5 variants per parent.
- A costume change never changes the face on its own: a
  derivative's face record is inherited from its parent unless
  the face is explicitly listed as changed.
- A shot waiting for material is marked pending material and
  the episode is not ready for generation. Missing material is
  never papered over with a placeholder asset.

This module stores records only. It generates no pictures, and
it never invents a face, a view or a scene skeleton that the
caller did not supply.

Method ideas borrowed, text self-written, from
HBAI-Ltd/Toonflow-app (MIT, verified against the repository
LICENSE file; the MIT licence covers that repository only, not
model services or generated material). No Toonflow text, code or
assets are copied here.
"""

from __future__ import annotations

import copy
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

KINDS = ("character", "scene", "prop")
CHARACTER_VIEWS = ("face_closeup", "front", "side", "back")
MAX_VARIANTS_PER_PARENT = 5
DEFAULT_NO_DERIVATIVE = (
    "instant_expression",
    "local_closeup",
    "camera_move",
    "weather",
    "damage",
)


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise CapabilityError(
            f"story.asset_registry_v2: {what} must be a non-empty string"
        )
    return value


def new_registry() -> dict[str, Any]:
    """Start an empty three-layer registry."""
    return {"assets": {}, "episodes": {}, "aliases": {}}


def _get_asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    asset = registry.get("assets", {}).get(asset_id)
    if not isinstance(asset, dict):
        raise CapabilityError(
            f"story.asset_registry_v2: unknown asset {asset_id!r}"
        )
    return asset


def resolve_name(registry: dict[str, Any], name: str) -> str:
    """Resolve a name or alias to the one master asset id."""
    name = _req_str(name, "name")
    if name in registry.get("aliases", {}):
        return str(registry["aliases"][name])
    for asset_id, asset in registry.get("assets", {}).items():
        if asset.get("name") == name:
            return str(asset_id)
    raise CapabilityError(
        f"story.asset_registry_v2: no asset or alias named {name!r}"
    )


def add_alias(registry: dict[str, Any], alias: str, asset_id: str) -> dict[str, Any]:
    """Point an alternate name at an existing master asset."""
    alias = _req_str(alias, "alias")
    _get_asset(registry, asset_id)
    existing = registry["aliases"].get(alias)
    if existing is not None and existing != asset_id:
        raise CapabilityError(
            f"story.asset_registry_v2: alias {alias!r} already points "
            f"to {existing!r}, not {asset_id!r}; aliases never merge "
            f"two different assets"
        )
    registry["aliases"][alias] = asset_id
    return registry


def register_asset(
    registry: dict[str, Any],
    asset_id: str,
    kind: str,
    name: str,
    *,
    views: Any = None,
    scene_skeleton: Any = None,
    light: Any = None,
) -> dict[str, Any]:
    """Register one master asset. The caller supplies all facts.

    Characters need all four views. Scenes need a skeleton and
    a light. Props need neither, but may carry views. A name
    already held by a different asset fails: use add_alias for
    another name of the same asset.
    """
    asset_id = _req_str(asset_id, "asset_id")
    name = _req_str(name, "name")
    if kind not in KINDS:
        raise CapabilityError(
            f"story.asset_registry_v2: kind {kind!r} is unknown; "
            f"known kinds: {list(KINDS)}"
        )
    if asset_id in registry["assets"]:
        raise CapabilityError(
            f"story.asset_registry_v2: asset {asset_id!r} already exists"
        )
    for other_id, other in registry["assets"].items():
        if other.get("name") == name:
            raise CapabilityError(
                f"story.asset_registry_v2: name {name!r} already "
                f"belongs to asset {other_id!r}; a second asset with "
                f"the same name is a different entity, so give it a "
                f"different name or declare an alias for {other_id!r}"
            )
    views = dict(views or {})
    if kind == "character":
        missing = [v for v in CHARACTER_VIEWS if v not in views]
        if missing:
            raise CapabilityError(
                f"story.asset_registry_v2: character {asset_id!r} is "
                f"missing views {missing}; a character master needs "
                f"face_closeup, front, side and back"
            )
    if kind == "scene":
        if not isinstance(scene_skeleton, dict) or not scene_skeleton:
            raise CapabilityError(
                f"story.asset_registry_v2: scene {asset_id!r} needs a "
                f"fixed skeleton describing its spatial layout"
            )
        if not isinstance(light, str) or not light:
            raise CapabilityError(
                f"story.asset_registry_v2: scene {asset_id!r} needs a "
                f"light description"
            )
    registry["assets"][asset_id] = {
        "asset_id": asset_id,
        "kind": kind,
        "name": name,
        "views": copy.deepcopy(views),
        "scene_skeleton": copy.deepcopy(scene_skeleton),
        "light": light,
        "derivatives": [],
    }
    return registry


def add_derivative(
    registry: dict[str, Any],
    parent_id: str,
    variant_id: str,
    *,
    changed: Any,
    unchanged: Any,
    allow_boundary: bool = False,
) -> dict[str, Any]:
    """Add one variant of a master asset, with its parent named.

    ``changed`` and ``unchanged`` are lists of aspect names.
    By default, boundary aspects (instant expression, local
    close-up, camera move, weather, damage) do not get their own
    derivative; pass allow_boundary=True to declare the exception
    explicitly. At most 5 variants per parent.
    """
    parent = _get_asset(registry, parent_id)
    variant_id = _req_str(variant_id, "variant_id")
    if not isinstance(changed, list) or not all(
        isinstance(c, str) for c in changed
    ):
        raise CapabilityError(
            "story.asset_registry_v2: changed must be a list of strings"
        )
    if not isinstance(unchanged, list) or not all(
        isinstance(c, str) for c in unchanged
    ):
        raise CapabilityError(
            "story.asset_registry_v2: unchanged must be a list of strings"
        )
    overlap = sorted(set(changed) & set(unchanged))
    if overlap:
        raise CapabilityError(
            f"story.asset_registry_v2: derivative {variant_id!r} lists "
            f"{overlap} as both changed and unchanged"
        )
    if not allow_boundary:
        blocked = [c for c in changed if c in DEFAULT_NO_DERIVATIVE]
        if blocked:
            raise CapabilityError(
                f"story.asset_registry_v2: derivative {variant_id!r} "
                f"would be created for boundary aspects {blocked}, "
                f"which by default do not get a derivative; use the "
                f"parent as-is, or pass allow_boundary=True to declare "
                f"the exception explicitly"
            )
    if len(parent["derivatives"]) >= MAX_VARIANTS_PER_PARENT:
        raise CapabilityError(
            f"story.asset_registry_v2: parent {parent_id!r} already "
            f"has {MAX_VARIANTS_PER_PARENT} variants; no more are added"
        )
    if variant_id in registry["assets"]:
        raise CapabilityError(
            f"story.asset_registry_v2: asset {variant_id!r} already exists"
        )
    parent_views = parent.get("views", {}) or {}
    face_record = parent_views.get("face_closeup")
    if "face" in changed:
        face_record = None
    variant = {
        "asset_id": variant_id,
        "kind": parent["kind"],
        "name": parent["name"],
        "parent_id": parent_id,
        "changed": list(changed),
        "unchanged": list(unchanged),
        "face_closeup": copy.deepcopy(face_record),
        "derivatives": [],
    }
    registry["assets"][variant_id] = variant
    parent["derivatives"].append(variant_id)
    return registry


def reference_asset(
    registry: dict[str, Any], episode_id: str, asset_id: str
) -> dict[str, Any]:
    """Record that an episode uses a master asset, by reference.

    Only the asset id is stored in the episode record. No copy
    of the asset's views, skeleton or light is made, so a later
    master change cannot leave an episode pointing at stale art
    without anyone noticing: the episode still points at the
    same master id.
    """
    _get_asset(registry, asset_id)
    episode = registry["episodes"].setdefault(
        _req_str(episode_id, "episode_id"),
        {"episode_id": episode_id, "references": [], "pending_material": []},
    )
    if asset_id not in episode["references"]:
        episode["references"].append(asset_id)
    return registry


def mark_pending_material(
    registry: dict[str, Any],
    episode_id: str,
    shot_id: str,
    asset_id: str,
    reason: str,
) -> dict[str, Any]:
    """Mark a shot as waiting for material. It must not generate."""
    episode = registry["episodes"].setdefault(
        _req_str(episode_id, "episode_id"),
        {"episode_id": episode_id, "references": [], "pending_material": []},
    )
    episode["pending_material"].append({
        "shot_id": _req_str(shot_id, "shot_id"),
        "asset_id": _req_str(asset_id, "asset_id"),
        "reason": _req_str(reason, "reason"),
    })
    return registry


def check_episode(registry: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Is this episode ready for generation, and what is missing?"""
    episode = registry.get("episodes", {}).get(episode_id)
    if not isinstance(episode, dict):
        raise CapabilityError(
            f"story.asset_registry_v2: unknown episode {episode_id!r}"
        )
    pending = episode.get("pending_material", [])
    return {
        "episode_id": episode_id,
        "ready": not pending,
        "references": list(episode.get("references", [])),
        "pending_material": copy.deepcopy(pending),
    }


def assert_episode_ready(registry: dict[str, Any], episode_id: str) -> dict[str, Any]:
    """Raise when an episode still waits for material."""
    report = check_episode(registry, episode_id)
    if not report["ready"]:
        shots = sorted({p["shot_id"] for p in report["pending_material"]})
        raise CapabilityError(
            f"story.asset_registry_v2: episode {episode_id!r} is not "
            f"ready for generation; shots waiting for material: {shots}"
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    registry = params.get("registry")
    if not isinstance(registry, dict):
        raise CapabilityError(
            "story.asset_registry_v2: registry must be an object"
        )
    episode_id = params.get("episode_id")
    report = (
        check_episode(registry, episode_id)
        if episode_id
        else {
            "assets": sorted(registry.get("assets", {})),
            "episodes": sorted(registry.get("episodes", {})),
        }
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "asset_registry_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path)},
    )


def register_asset_registry_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.asset_registry_v2",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "registry": {"type": "object"},
                    "episode_id": {"type": "string"},
                },
                "required": ["registry"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Three-layer asset registry: script, master assets "
                "and episode references. One master per asset, "
                "episodes store references only, names never merge "
                "two different entities, characters carry face "
                "close-up plus front/side/back views, scenes carry "
                "a fixed skeleton and light, derivatives name "
                "their parent and changed/unchanged aspects with "
                "a default extraction boundary and at most 5 "
                "variants per parent, and shots waiting for "
                "material block generation. Records only; "
                "generates nothing itself."
            ),
            line="story",
        )
    )
    return ["story.asset_registry_v2"]


register_asset_registry_capabilities_once()
