"""Camera movement index (``video.camera_movement_index``).

Unified index over the single source
``cinematic_data/camera_movements.json``: the full 46-movement
library from aicameramovements.com, restated in hevi's own wording
(40 taken in on 2026-10-25, 6 added 2026-11-04). No second copy of
the catalogue exists: this module reads the same JSON that
``shot.camera_movements`` and ``story.prompt_compiler`` read, and
only derives extra per-entry fields (mechanism family, special
applicability flag, render-verification flag).

Every entry records ``verified_by_hevi_render: false``: this index
asserts identity, category and wording provenance, never that hevi
has rendered a movement. The 124 shotcraft cards are a different
library (Remotion effect cards); shared generic words such as
``push_past`` take their meaning here from the physical camera
definition, never from the card library. No site prompt text is
copied here. See CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.zoom_track_distinction_gate import classify_mechanism

_Registered = False

_INDEX_SOURCE = "aicameramovements.com (method restated in hevi wording)"

# The six movements added by the 2026-11-04 completion, with the
# site category each belongs to.
NEW_MOVEMENT_IDS: frozenset[str] = frozenset(
    {
        "helicopter_shot",
        "tilt_shift",
        "infinite_zoom",
        "earth_zoom_out",
        "time_lapse",
        "pass_through_objects",
    }
)

EXPECTED_NEW_CATEGORIES: dict[str, str] = {
    "helicopter_shot": "Drone/Crane",
    "tilt_shift": "Specials",
    "infinite_zoom": "Specials",
    "earth_zoom_out": "Specials",
    "time_lapse": "Specials",
    "pass_through_objects": "Specials",
}

EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "Pan/Tilt": 7,
    "Zoom/Lens": 6,
    "Dolly/Track": 9,
    "Physical Moves": 11,
    "Human Camera": 2,
    "Drone/Crane": 5,
    "Specials": 6,
}

CATEGORIES: tuple[str, ...] = tuple(EXPECTED_CATEGORY_COUNTS)

# Composite/time-class effects: not single physical moves. The value
# names the declaration a plan must carry (see the flag gate).
SPECIAL_FLAGS: dict[str, str] = {
    "earth_zoom_out": "composite_segments",
    "infinite_zoom": "composite_segments",
    "time_lapse": "time_compression",
}

FOUR_FIELDS = ("movement", "speed", "framing", "end")


def _enrich(entry: dict[str, Any]) -> dict[str, Any]:
    movement_id = str(entry.get("id", ""))
    enriched = dict(entry)
    enriched["mechanism"] = classify_mechanism(movement_id)
    enriched["special_flag"] = SPECIAL_FLAGS.get(movement_id)
    enriched["is_completion_movement"] = movement_id in NEW_MOVEMENT_IDS
    enriched["verified_by_hevi_render"] = False
    enriched["index_source"] = _INDEX_SOURCE
    return enriched


def list_camera_movements(category: str | None = None) -> list[dict[str, Any]]:
    """Return enriched index entries, optionally filtered by category."""
    rows = load_movements()
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return [_enrich(r) for r in rows]


def get_camera_movement(movement_id: str) -> dict[str, Any] | None:
    """Return one enriched index entry by id, or None when absent."""
    for row in load_movements():
        if row["id"] == movement_id:
            return _enrich(row)
    return None


def check_movement_index() -> dict[str, Any]:
    """Validate the unified index itself. Returns a report; never raises."""
    issues: list[str] = []
    rows = load_movements()
    expected_total = sum(EXPECTED_CATEGORY_COUNTS.values())
    if len(rows) != expected_total:
        issues.append(f"movement_count_not_{expected_total}:{len(rows)}")
    ids = [r.get("id") for r in rows if isinstance(r, dict)]
    if len(ids) != len(set(ids)):
        issues.append("duplicate_ids")
    from collections import Counter

    counts = Counter(r.get("category") for r in rows)
    for category, want in EXPECTED_CATEGORY_COUNTS.items():
        if counts.get(category, 0) != want:
            issues.append(
                f"category_count:{category}:{counts.get(category, 0)}!={want}"
            )
    for unknown in sorted(set(counts) - set(EXPECTED_CATEGORY_COUNTS)):
        issues.append(f"unknown_category:{unknown}")
    for row in rows:
        if not isinstance(row, dict):
            issues.append("entry_not_object")
            continue
        for field in FOUR_FIELDS:
            if not str(row.get(field, "")).strip():
                issues.append(f"field_blank:{row.get('id')}:{field}")
        if row.get("id") in NEW_MOVEMENT_IDS and row.get("category") != (
            EXPECTED_NEW_CATEGORIES.get(str(row.get("id")))
        ):
            issues.append(f"new_movement_category:{row.get('id')}")
        if classify_mechanism(str(row.get("id", ""))) not in (
            "zoom",
            "body",
            "other",
        ):
            issues.append(f"mechanism_unclassified:{row.get('id')}")
    flagged = {r["id"] for r in rows if r.get("id") in SPECIAL_FLAGS}
    if flagged != set(SPECIAL_FLAGS):
        issues.append("special_flag_set_mismatch")
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "movement_count": len(rows),
        "category_count": len(counts),
        "category_counts": dict(counts),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = str(params.get("action", "list"))
    if action == "get":
        payload: dict[str, Any] = {
            "movement": get_camera_movement(str(params.get("movement", "")))
        }
    elif action == "check":
        payload = {"index_check": check_movement_index()}
    else:
        category = params.get("category")
        payload = {
            "movements": list_camera_movements(
                str(category) if isinstance(category, str) else None
            ),
            "index_check": check_movement_index(),
        }
    report_path = out_dir / "camera_movement_index.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "action": action},
    )


def register_camera_movement_index_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.camera_movement_index",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "get", "check"],
                    },
                    "category": {"type": "string"},
                    "movement": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="obase",
            description=(
                "Camera movement index: the unified 46-movement "
                "index over the single-source catalogue (40 taken in "
                "2026-10-25, 6 completion movements added 2026-11-04), "
                "with mechanism family and special-flag derivation; "
                "identity and provenance only, nothing recorded as "
                "rendered by hevi."
            ),
        )
    )
    return ["video.camera_movement_index"]


__all__ = [
    "CATEGORIES",
    "EXPECTED_CATEGORY_COUNTS",
    "EXPECTED_NEW_CATEGORIES",
    "NEW_MOVEMENT_IDS",
    "SPECIAL_FLAGS",
    "list_camera_movements",
    "get_camera_movement",
    "check_movement_index",
    "register_camera_movement_index_capabilities_once",
]
