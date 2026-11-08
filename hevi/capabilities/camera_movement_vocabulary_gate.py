"""Camera movement vocabulary gate (``qa.camera_movement_vocabulary_gate``).

Clean-room discipline gate only. The camera movement vocabulary is
the single source in ``cinematic_data/camera_movements.json``: the
full 46-movement library from aicameramovements.com, restated in
hevi's own wording (40 taken in on 2026-10-25, 6 added 2026-11-04).
This gate judges vocabulary membership only and renders nothing:

* the loaded catalogue must contain all 46 movements, including the
  six added by the 2026-11-04 completion (``helicopter_shot``,
  ``tilt_shift``, ``infinite_zoom``, ``earth_zoom_out``,
  ``time_lapse``, ``pass_through_objects``), each in its site
  category, with all four fields present;
* no duplicate ids; a claimed movement id outside the closed
  vocabulary fails.

The six new definitions are hevi's own paraphrases of the physical
movement (see ``camera_movement_index``); no site prompt text is
copied anywhere in this graft. See CAMERA_MOVEMENTS_ATTRIBUTION.md.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.camera_movement_index import (
    EXPECTED_CATEGORY_COUNTS,
    EXPECTED_NEW_CATEGORIES,
    NEW_MOVEMENT_IDS,
)
from hevi.capabilities.cinematic_techniques import load_movements
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from pathlib import Path
import json

_Registered = False

FOUR_FIELDS = ("movement", "speed", "framing", "end")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def vocabulary_ids(entries: list[dict[str, Any]] | None = None) -> frozenset[str]:
    """Return the closed vocabulary ids from the loaded catalogue."""
    rows = entries if entries is not None else load_movements()
    return frozenset(str(r.get("id", "")) for r in rows if isinstance(r, dict))


def check_movement_vocabulary(
    claimed_ids: list[str] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate the movement vocabulary. Returns a report; never raises.

    With no arguments the loaded catalogue itself is checked: 46
    entries, the six completion movements present in their categories,
    no duplicate ids. With ``claimed_ids`` every claimed id must also
    be a member of the closed vocabulary.
    """
    issues: list[dict[str, Any]] = []
    rows = entries if entries is not None else load_movements()
    rows = [r for r in rows if isinstance(r, dict)]
    ids = [str(r.get("id", "")) for r in rows]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        issues.append(
            _issue("duplicate_ids", f"duplicate movement ids: {dupes}")
        )
    expected_total = sum(EXPECTED_CATEGORY_COUNTS.values())
    if len(rows) != expected_total:
        issues.append(
            _issue(
                "vocabulary_count_not_46",
                f"catalogue holds {len(rows)} movements, want {expected_total}",
            )
        )
    by_id = {str(r.get("id", "")): r for r in rows}
    for movement_id in sorted(NEW_MOVEMENT_IDS):
        entry = by_id.get(movement_id)
        if entry is None:
            issues.append(
                _issue(
                    f"new_movement_missing:{movement_id}",
                    f"completion movement {movement_id!r} is absent "
                    "from the catalogue",
                )
            )
            continue
        want_category = EXPECTED_NEW_CATEGORIES[movement_id]
        if entry.get("category") != want_category:
            issues.append(
                _issue(
                    f"new_movement_category:{movement_id}",
                    f"{movement_id!r} is in category {entry.get('category')!r}, "
                    f"want {want_category!r}",
                )
            )
        for field in FOUR_FIELDS:
            if not str(entry.get(field, "")).strip():
                issues.append(
                    _issue(
                        f"new_movement_field_missing:{movement_id}:{field}",
                        f"{movement_id!r} is missing four-field entry {field!r}",
                    )
                )
    vocabulary = set(ids)
    for claimed in claimed_ids or []:
        if claimed not in vocabulary:
            issues.append(
                _issue(
                    f"unknown_movement_id:{claimed}",
                    f"{claimed!r} is not in the closed 46-movement vocabulary",
                )
            )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "vocabulary_size": len(set(ids)),
        "new_movements_found": sorted(NEW_MOVEMENT_IDS & set(ids)),
        "new_movements_wanted": sorted(NEW_MOVEMENT_IDS),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    claimed = params.get("claimed_ids")
    report = check_movement_vocabulary(
        list(claimed) if isinstance(claimed, list) else None
    )
    report_path = out_dir / "camera_movement_vocabulary.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_camera_movement_vocabulary_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.camera_movement_vocabulary_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claimed_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Camera movement vocabulary gate: the catalogue must "
                "hold all 46 movements including the six completion "
                "movements in their categories, with no duplicate ids, "
                "and every claimed movement id must be in the closed "
                "vocabulary."
            ),
        )
    )
    return ["qa.camera_movement_vocabulary_gate"]


__all__ = [
    "check_movement_vocabulary",
    "vocabulary_ids",
    "register_camera_movement_vocabulary_gate_capabilities_once",
]
