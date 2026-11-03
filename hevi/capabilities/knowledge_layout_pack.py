"""Knowledge layout pack (``video.knowledge_layout_pack``).

Clean-room restatement of the method in ``hevi-vs-explainer-skills-9.md``
section 2 item 3 (Knowledge Explainer): six built-in page layouts, each
described in hevi's own words as a zone map over a 1280x720 page, plus
two caller-defined custom slots. No template code is copied and no
renderer is invoked:

* title -- one centred headline zone with a subtitle zone below it.
* content_card -- a headline zone over a row of content cards.
* two_column -- a headline zone over two equal content columns.
* triangle -- three zones arranged as a triangle: apex, left base,
  right base.
* before_after -- two zones side by side, labelled before and after.
* outro -- one centred closing zone with a call-to-action zone.

``render_layout_fake`` produces one deterministic frame record per
layout: the sha256 of the canonical layout spec plus the frame index,
marked ``backend: fake``. It runs no browser and no Remotion; the
frame record proves the layout spec is well formed and reproducible,
never that pixels were produced. A real render would go through
``video.minimal_stage_render`` and is a separate case.
"""

from __future__ import annotations

import hashlib
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

PAGE_WIDTH = 1280
PAGE_HEIGHT = 720

LAYOUTS: dict[str, dict[str, Any]] = {
    "title": {
        "description": "One centred headline zone with a subtitle zone below it.",
        "zones": [
            {"name": "headline", "x": 140, "y": 240, "w": 1000, "h": 120},
            {"name": "subtitle", "x": 240, "y": 380, "w": 800, "h": 60},
        ],
    },
    "content_card": {
        "description": "A headline zone over a row of content cards.",
        "zones": [
            {"name": "headline", "x": 80, "y": 60, "w": 1120, "h": 90},
            {"name": "card_1", "x": 80, "y": 200, "w": 340, "h": 400},
            {"name": "card_2", "x": 470, "y": 200, "w": 340, "h": 400},
            {"name": "card_3", "x": 860, "y": 200, "w": 340, "h": 400},
        ],
    },
    "two_column": {
        "description": "A headline zone over two equal content columns.",
        "zones": [
            {"name": "headline", "x": 80, "y": 60, "w": 1120, "h": 90},
            {"name": "column_left", "x": 80, "y": 200, "w": 540, "h": 400},
            {"name": "column_right", "x": 660, "y": 200, "w": 540, "h": 400},
        ],
    },
    "triangle": {
        "description": "Three zones arranged as a triangle: apex, left base, right base.",
        "zones": [
            {"name": "apex", "x": 490, "y": 80, "w": 300, "h": 180},
            {"name": "base_left", "x": 180, "y": 400, "w": 380, "h": 200},
            {"name": "base_right", "x": 720, "y": 400, "w": 380, "h": 200},
        ],
    },
    "before_after": {
        "description": "Two zones side by side, labelled before and after.",
        "zones": [
            {"name": "before", "x": 80, "y": 140, "w": 540, "h": 440},
            {"name": "after", "x": 660, "y": 140, "w": 540, "h": 440},
        ],
    },
    "outro": {
        "description": "One centred closing zone with a call-to-action zone.",
        "zones": [
            {"name": "closing", "x": 240, "y": 240, "w": 800, "h": 120},
            {"name": "call_to_action", "x": 340, "y": 400, "w": 600, "h": 60},
        ],
    },
}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def list_layouts() -> list[str]:
    """Return the built-in layout names in pack order."""
    return list(LAYOUTS)


def get_layout(name: Any) -> dict[str, Any]:
    """Return one layout's zone map, or raise for an unknown layout."""
    if not _is_nonempty_str(name) or name not in LAYOUTS:
        raise CapabilityError(
            "video.knowledge_layout_pack: unknown layout "
            f"{name!r}; known layouts are {', '.join(LAYOUTS)}"
        )
    entry = json.loads(json.dumps(LAYOUTS[name], ensure_ascii=False))
    entry["name"] = name
    entry["page"] = {"width": PAGE_WIDTH, "height": PAGE_HEIGHT}
    return entry


def build_layout(name: Any, content: Any) -> dict[str, Any]:
    """Bind caller content to a layout's zones and validate the binding.

    Custom layouts are caller-defined slots: the caller supplies a
    ``custom`` layout name and its own zone map. A custom zone map
    must stay inside the 1280x720 page.
    """
    if not isinstance(content, dict):
        raise CapabilityError(
            "video.knowledge_layout_pack: content must be a JSON object"
        )
    if _is_nonempty_str(name) and name in LAYOUTS:
        spec = get_layout(name)
    elif isinstance(name, dict) and _is_nonempty_str(name.get("custom_name")):
        zones = name.get("zones")
        if not isinstance(zones, list) or not zones:
            raise CapabilityError(
                "video.knowledge_layout_pack: a custom layout must declare "
                "a non-empty zones list"
            )
        for zone in zones:
            if not isinstance(zone, dict):
                raise CapabilityError(
                    "video.knowledge_layout_pack: zones must be objects"
                )
            for key in ("name", "x", "y", "w", "h"):
                if key not in zone:
                    raise CapabilityError(
                        "video.knowledge_layout_pack: every zone must declare "
                        "name, x, y, w, h"
                    )
            if (
                zone["x"] < 0
                or zone["y"] < 0
                or zone["x"] + zone["w"] > PAGE_WIDTH
                or zone["y"] + zone["h"] > PAGE_HEIGHT
            ):
                raise CapabilityError(
                    "video.knowledge_layout_pack: custom zone "
                    f"{zone['name']!r} leaves the 1280x720 page"
                )
        spec = {
            "name": name["custom_name"],
            "custom": True,
            "description": "Caller-defined custom layout.",
            "zones": zones,
            "page": {"width": PAGE_WIDTH, "height": PAGE_HEIGHT},
        }
    else:
        raise CapabilityError(
            "video.knowledge_layout_pack: unknown layout "
            f"{name!r}; known layouts are {', '.join(LAYOUTS)}"
        )
    zone_names = [zone["name"] for zone in spec["zones"]]
    missing = [zone for zone in zone_names if zone not in content]
    if missing:
        raise CapabilityError(
            "video.knowledge_layout_pack: content is missing zones "
            f"{missing} for layout {spec['name']!r}"
        )
    spec["content"] = {zone: content[zone] for zone in zone_names}
    return spec


def render_layout_fake(spec: Any, *, frames: int = 1) -> dict[str, Any]:
    """Produce deterministic fake frame records for one layout spec.

    No browser runs and no renderer loads; each record is the sha256
    of the canonical spec plus the frame index.
    """
    if not isinstance(spec, dict) or "zones" not in spec:
        raise CapabilityError(
            "video.knowledge_layout_pack: spec must be a layout spec from "
            "build_layout"
        )
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    frame_records = []
    for index in range(frames):
        digest = hashlib.sha256(
            f"{canonical}|frame:{index}".encode("utf-8")
        ).hexdigest()
        frame_records.append({"frame": index, "sha256": digest, "backend": "fake"})
    return {
        "backend": "fake",
        "layout": spec.get("name"),
        "frames": frame_records,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    spec = build_layout(params.get("name"), params.get("content"))
    record = render_layout_fake(spec)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "knowledge_layout_pack_record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(record_path),
        qa={
            "report_json": str(record_path),
            "ok": True,
            "backend": "fake",
        },
    )


def register_knowledge_layout_pack_capabilities_once() -> list[str]:
    """Register the layout pack on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.knowledge_layout_pack",
            kind="line",
            aspects=["16:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "name": {},
                    "content": {"type": "object"},
                },
                "required": ["name", "content"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Knowledge layout pack: six built-in page layouts plus "
                "caller-defined custom slots, each as a zone map over a "
                "1280x720 page. Fake frame records only; no renderer is "
                "invoked."
            ),
            line="video",
        )
    )
    return ["video.knowledge_layout_pack"]


register_knowledge_layout_pack_capabilities_once()
