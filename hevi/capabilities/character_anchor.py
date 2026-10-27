"""One anchor, many views: character reference discipline without generating images.

Method idea (clean-room reimplementation, see
SHUOHAO_METHOD_ATTRIBUTION.md): a character's reference set has
exactly one root -- one front, full-body anchor. Every other view
(headshot, profile, back, detail) derives from that anchor alone
and never from another view, so a bad view can be remade on its
own without a chain reaction. Only three things are frozen: the
anchor file, the look snapshot, and the description fingerprint.
Change any one of them and every current view is marked stale --
flagged, never deleted, so old versions stay available for
comparison. An anchor that has not been confirmed by a human
blocks the set from production.

This module contains no image generation and no model call of
any kind. It does not know or care which tool produced a picture;
hevi's picture route stays whatever it already is. The sheet
records file hashes supplied by the caller, so the same sheet
works whether the pictures came from a free route, a local
model, or a hand-drawn scan. A view's ``derives_from`` is always
the literal string ``"anchor"``; anything else is a chain
reference and is rejected outright.

Failure contract: sheets, anchors and views must be JSON objects
with non-empty string ids, names, files and hashes; violations
raise CapabilityError. Gate failures (no anchor, unconfirmed
anchor, stale current views, missing expected views) are
reported, not raised, except adding a view to an unconfirmed or
missing anchor, which raises because it would create a view with
no trustworthy root.
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


def description_fingerprint(text: str) -> str:
    """Stable fingerprint for a character description (caller text only)."""
    if not isinstance(text, str):
        raise CapabilityError("qa.character_anchor_gate: description must be a string")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _req_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"qa.character_anchor_gate: {what} must be a non-empty string")
    return value.strip()


def new_sheet(character_id: str, name: str) -> dict[str, Any]:
    """Start an empty reference sheet for one character."""
    return {"character_id": _req_str(character_id, "character_id"),
            "name": _req_str(name, "name"),
            "anchor": None, "views": [], "anchor_changes": 0}


def _check_sheet_shape(sheet: dict[str, Any]) -> None:
    if not isinstance(sheet, dict):
        raise CapabilityError("qa.character_anchor_gate: sheet must be a JSON object")
    _req_str(sheet.get("character_id"), "sheet.character_id")
    _req_str(sheet.get("name"), "sheet.name")
    if not isinstance(sheet.get("views"), list):
        raise CapabilityError("qa.character_anchor_gate: sheet.views must be a list")
    for view in sheet["views"]:
        if not isinstance(view, dict):
            raise CapabilityError("qa.character_anchor_gate: every view must be a JSON object")


def set_anchor(sheet: dict[str, Any], *, file: str, sha256: str,
               look_snapshot: str, description_fingerprint: str) -> dict[str, Any]:
    """Set (or replace) the sheet's single anchor.

    Replacing an anchor whose frozen fields differ from the old
    one marks every current view stale and counts one anchor
    change. Nothing is deleted: stale views stay in the list.
    The new anchor starts unconfirmed and must be confirmed
    before any new view is added.
    """
    _check_sheet_shape(sheet)
    new_anchor = {"file": _req_str(file, "anchor.file"),
                  "sha256": _req_str(sha256, "anchor.sha256"),
                  "look_snapshot": _req_str(look_snapshot, "anchor.look_snapshot"),
                  "description_fingerprint": _req_str(description_fingerprint, "anchor.description_fingerprint"),
                  "confirmed": False}
    old = sheet.get("anchor")
    if isinstance(old, dict) and any(old.get(k) != new_anchor[k] for k in
                                     ("file", "sha256", "look_snapshot", "description_fingerprint")):
        sheet["anchor_changes"] = int(sheet.get("anchor_changes", 0)) + 1
        for view in sheet["views"]:
            if view.get("status") == "current":
                view["status"] = "stale"
    sheet["anchor"] = new_anchor
    return sheet


def confirm_anchor(sheet: dict[str, Any]) -> dict[str, Any]:
    """Mark the current anchor confirmed by a human reviewer."""
    _check_sheet_shape(sheet)
    if not isinstance(sheet.get("anchor"), dict):
        raise CapabilityError("qa.character_anchor_gate: no anchor to confirm")
    sheet["anchor"]["confirmed"] = True
    return sheet


def add_view(sheet: dict[str, Any], *, view: str, file: str, sha256: str,
             model: str | None = None, derives_from: str | None = None) -> dict[str, Any]:
    """Add one view derived from the anchor only.

    ``derives_from`` may be omitted or ``"anchor"``; any other
    value is a chain reference (view derived from view) and is
    rejected. Re-adding an existing view supersedes the previous
    current record for that view instead of deleting it.
    """
    _check_sheet_shape(sheet)
    anchor = sheet.get("anchor")
    if not isinstance(anchor, dict):
        raise CapabilityError("qa.character_anchor_gate: cannot add a view without an anchor")
    if anchor.get("confirmed") is not True:
        raise CapabilityError("qa.character_anchor_gate: anchor must be confirmed before adding a view")
    if derives_from is not None and derives_from != "anchor":
        raise CapabilityError(
            f"qa.character_anchor_gate: view {view!r} derives from {derives_from!r}, "
            "views may only derive from the anchor")
    view_name = _req_str(view, "view")
    record = {"view": view_name, "file": _req_str(file, "view.file"),
              "sha256": _req_str(sha256, "view.sha256"),
              "derives_from": "anchor", "model": model, "status": "current"}
    for old in sheet["views"]:
        if old.get("view") == view_name and old.get("status") == "current":
            old["status"] = "superseded"
    sheet["views"].append(record)
    return sheet


def check_anchor_sheet(sheet: dict[str, Any], expected_views: list[str] | None = None) -> dict[str, Any]:
    """Judge a reference sheet. Verdicts: pass, needs_regeneration, fail."""
    _check_sheet_shape(sheet)
    issues: list[dict[str, Any]] = []
    anchor = sheet.get("anchor")
    if not isinstance(anchor, dict):
        issues.append({"code": "ANCHOR_SINGLE", "message": "sheet has no anchor"})
        return {"verdict": "fail", "issues": issues, "stale_views": [],
                "current_views": [], "anchor_confirmed": False}
    if anchor.get("confirmed") is not True:
        issues.append({"code": "ANCHOR_CONFIRMED", "message": "anchor is not confirmed"})
    current: dict[str, dict[str, Any]] = {}
    for view in sheet["views"]:
        if view.get("derives_from") != "anchor":
            issues.append({"code": "DERIVE_ANCHOR_ONLY",
                           "message": f"view {view.get('view')!r} does not derive from the anchor"})
        if view.get("status") == "current":
            if view["view"] in current:
                issues.append({"code": "VIEW_SINGLE_CURRENT",
                               "message": f"view {view['view']!r} has more than one current record"})
            current[view["view"]] = view
    stale = sorted(v["view"] for v in sheet["views"] if v.get("status") == "stale")
    if stale:
        issues.append({"code": "STALE_VIEWS", "message": f"stale views need regeneration: {', '.join(stale)}"})
    if expected_views is not None:
        missing = [v for v in expected_views if v not in current]
        if missing:
            issues.append({"code": "VIEW_COVERAGE", "message": f"missing views: {', '.join(missing)}"})
    fatal = any(i["code"] in ("ANCHOR_SINGLE", "ANCHOR_CONFIRMED",
                              "DERIVE_ANCHOR_ONLY", "VIEW_SINGLE_CURRENT") for i in issues)
    verdict = "fail" if fatal else ("needs_regeneration" if issues else "pass")
    return {"verdict": verdict, "issues": issues, "stale_views": stale,
            "current_views": sorted(current), "anchor_confirmed": anchor.get("confirmed") is True}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_anchor_sheet(params.get("sheet"), params.get("expected_views"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "character_anchor_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"],
            "current_views": result["current_views"]},
    )


def register_character_anchor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.character_anchor_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"sheet": {"type": "object"},
                           "expected_views": {"type": "array"}},
            "required": ["sheet"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Character anchor gate (clean-room): one confirmed front "
            "full-body anchor is the only root; every view derives from "
            "it alone, anchor changes mark views stale without deleting "
            "them. No image is generated here."
        ),
        line="qa",
    ))
    return ["qa.character_anchor_gate"]


register_character_anchor_capabilities_once()
