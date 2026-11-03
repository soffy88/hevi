"""User-asset script draft: ``story.asset_script``.

Pixelle-Video idea, hevi implementation (clean-room: no Pixelle-Video
code, text, or structure is copied). The user brings their own photos
or videos; a vision model (VLM) analyses them; hevi turns that analysis
into a script draft (scenes + shot points). This module sits beside
``story.reference_bundle`` / ``story.reference_decompose``: assets
registered here use the same ``asset_id`` vocabulary, so a registered
asset can later be cited as a ``story.reference_bundle`` registry key.

The VLM layer is injectable, exactly like the ``llm_fn`` contract in
``story.reference_decompose`` (``set_vlm_fn`` / ``set_llm_fn``):

* ``vlm_fn(asset) -> dict`` -- one asset dict in, one analysis dict
  out, with the structured fields ``people`` / ``scene`` / ``objects``
  / ``mood``. The capability render cannot receive a function through
  JSON params, so the render uses the module-level injected function.
* Default route: there is none. With no VLM installed the result is
  honestly ``status="pending"`` with ``draft=None`` and
  ``analysis=None`` -- never a fabricated analysis. In particular
  DashScope is NEVER a default: the account is in arrears, so this
  module never reads a DashScope key, never calls DashScope, and never
  falls back to it. A DashScope route may only appear as an explicitly
  injected ``vlm_fn`` supplied by the caller, after the account is
  settled -- the module itself will not invent one.
* A VLM failure (exception, non-dict return, or an analysis with all
  four fields empty) degrades to ``pending`` with the failure recorded
  in ``failures`` -- never a fake success, never a half draft.

The draft is deterministic data, not generation: every shot point is
built only from analysis fields the VLM actually returned. An empty
field produces no shot point for it; nothing is invented to fill a
scene. The draft is a readable plan -- no video is rendered and no
generation API is called by this module.
"""

from __future__ import annotations

import json
import re
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
_vlm_fn: Any = None

_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ASSET_KINDS = ("photo", "video")
_ASSET_KEYS = {"asset_id", "kind", "path", "note"}
_ANALYSIS_FIELDS = ("people", "scene", "objects", "mood")

_NO_VLM_NOTE = (
    "No VLM is configured: install one with "
    "hevi.capabilities.asset_script.set_vlm_fn(vlm_fn). "
    "DashScope is NOT used by default (account in arrears) and is "
    "never fallen back to; without an injected VLM this result stays "
    "pending and no analysis or draft is fabricated."
)


def set_vlm_fn(fn: Any) -> None:
    """Install a process-wide ``vlm_fn(asset) -> dict`` for analysis."""
    global _vlm_fn
    _vlm_fn = fn


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def register_assets(assets: Any) -> list[dict[str, Any]]:
    """Validate user-supplied assets; returns normalized copies.

    An empty list is refused: a script draft from zero assets would be
    a fake success. ``path`` is recorded, never read -- existence is
    not required here, so tests and callers may register assets whose
    files live elsewhere; the VLM (when injected) decides what to do
    with the path.
    """
    if not isinstance(assets, list) or not assets:
        raise CapabilityError(
            "story.asset_script: 'assets' must be a non-empty list "
            "(refusing to draft a script from zero user assets)"
        )
    normalized: list[dict[str, Any]] = []
    for raw in assets:
        if not isinstance(raw, dict):
            raise CapabilityError("story.asset_script: every asset must be an object")
        unknown = sorted(set(raw) - _ASSET_KEYS)
        if unknown:
            raise CapabilityError(
                f"story.asset_script: unknown asset keys {unknown}"
            )
        asset_id = raw.get("asset_id")
        if not isinstance(asset_id, str) or not _ASSET_ID_RE.match(asset_id):
            raise CapabilityError(
                "story.asset_script: asset_id must match "
                "[a-z0-9][a-z0-9_-]{0,63} (lowercase, registry-safe)"
            )
        kind = raw.get("kind")
        if kind not in ASSET_KINDS:
            raise CapabilityError(
                f"story.asset_script: asset {asset_id!r} kind must be one "
                f"of {list(ASSET_KINDS)}, got {kind!r}"
            )
        normalized.append(
            {
                "asset_id": asset_id,
                "kind": kind,
                "path": _as_str(raw.get("path")),
                "note": _as_str(raw.get("note")),
            }
        )
    seen = [a["asset_id"] for a in normalized]
    if len(seen) != len(set(seen)):
        raise CapabilityError("story.asset_script: duplicate asset_id in assets")
    return normalized


def _normalize_analysis(raw: Any, asset_id: str) -> dict[str, Any]:
    """Normalize one VLM analysis dict; bad shapes raise."""
    if not isinstance(raw, dict):
        raise CapabilityError(
            f"story.asset_script: VLM returned a non-dict analysis for "
            f"asset {asset_id!r} (got {type(raw).__name__}); refusing to "
            "treat it as an analysis"
        )
    out: dict[str, Any] = {"asset_id": asset_id}
    for field in ("people", "scene", "objects"):
        value = raw.get(field)
        if value is None:
            out[field] = []
        elif isinstance(value, str):
            out[field] = [value.strip()] if value.strip() else []
        elif isinstance(value, list):
            items: list[str] = []
            for raw_item in value:
                text = _as_str(raw_item).strip()
                if text:
                    items.append(text)
            out[field] = items
        else:
            raise CapabilityError(
                f"story.asset_script: VLM analysis field {field!r} for "
                f"asset {asset_id!r} must be a string or a list of strings"
            )
    mood = raw.get("mood")
    if mood is None:
        out["mood"] = ""
    elif isinstance(mood, str):
        out["mood"] = mood.strip()
    else:
        raise CapabilityError(
            f"story.asset_script: VLM analysis field 'mood' for asset "
            f"{asset_id!r} must be a string"
        )
    return out


def analyze_assets(
    assets: list[dict[str, Any]], vlm_fn: Any = None
) -> dict[str, Any]:
    """Run the injected VLM over registered assets, or report pending.

    Returns ``{status, analysis, failures, note}`` where status is
    ``ready`` (every asset analysed, at least one field non-empty) or
    ``pending`` (no VLM, a VLM failure, or an all-empty analysis).
    Pending never carries a draft -- callers must check ``status``.
    """
    registered = register_assets(assets)
    fn = vlm_fn if vlm_fn is not None else _vlm_fn
    if fn is None:
        return {
            "status": "pending",
            "analysis": None,
            "failures": ["no_vlm_configured"],
            "note": _NO_VLM_NOTE,
        }
    analyses: list[dict[str, Any]] = []
    failures: list[str] = []
    for asset in registered:
        try:
            analyses.append(_normalize_analysis(fn(dict(asset)), asset["asset_id"]))
        except Exception as exc:
            failures.append(f"{asset['asset_id']}: {exc}")
    if failures:
        return {
            "status": "pending",
            "analysis": None,
            "failures": failures,
            "note": (
                "VLM analysis failed for at least one asset; the result "
                "stays pending and no draft is produced, rather than a "
                "half-analysed draft pretending to be complete."
            ),
        }
    if not any(
        a["people"] or a["scene"] or a["objects"] or a["mood"] for a in analyses
    ):
        return {
            "status": "pending",
            "analysis": analyses,
            "failures": ["empty_analysis"],
            "note": (
                "VLM returned an analysis with all fields empty; the "
                "result stays pending and no draft is produced, rather "
                "than a draft invented from nothing."
            ),
        }
    return {
        "status": "ready",
        "analysis": analyses,
        "failures": [],
        "note": "VLM analysis complete for all registered assets.",
    }


def draft_script(analysis: list[dict[str, Any]], title: str = "") -> dict[str, Any]:
    """Build a readable script draft from a ready analysis only.

    Scenes are built per asset, in registration order: one establishing
    scene from its ``scene`` entries, then people introductions, then
    object details, closing with the mood line when one was given.
    Every shot point quotes an analysis field; no field, no point.
    """
    if not isinstance(analysis, list) or not analysis:
        raise CapabilityError(
            "story.asset_script: draft_script needs a non-empty analysis list"
        )
    scenes: list[dict[str, Any]] = []
    moods: list[str] = []
    for item in analysis:
        if not isinstance(item, dict):
            raise CapabilityError("story.asset_script: analysis items must be objects")
        asset_id = item.get("asset_id", "")
        points: list[str] = []
        for scene_text in item.get("scene") or []:
            points.append(f"定场：{scene_text}")
        for person in item.get("people") or []:
            points.append(f"人物入镜：{person}")
        for obj in item.get("objects") or []:
            points.append(f"物件特写：{obj}")
        if not points:
            continue
        focus_parts: list[str] = []
        if item.get("scene"):
            focus_parts.append("场景")
        if item.get("people"):
            focus_parts.append("人物")
        if item.get("objects"):
            focus_parts.append("物件")
        scenes.append(
            {
                "scene_no": len(scenes) + 1,
                "asset_id": asset_id,
                "focus": " / ".join(focus_parts),
                "shot_points": points,
            }
        )
        if item.get("mood"):
            moods.append(str(item["mood"]))
    if not scenes:
        raise CapabilityError(
            "story.asset_script: analysis carries no scene/people/object "
            "content to draft from; refusing to invent a draft"
        )
    draft: dict[str, Any] = {
        "title": title,
        "scenes": scenes,
        "shot_point_count": sum(len(s["shot_points"]) for s in scenes),
    }
    if moods:
        draft["tone"] = " / ".join(dict.fromkeys(moods))
        draft["scenes"].append(
            {
                "scene_no": len(scenes) + 1,
                "asset_id": "",
                "focus": "氛围",
                "shot_points": [f"全片氛围：{draft['tone']}"],
            }
        )
    return draft


def asset_script(
    assets: Any, vlm_fn: Any = None, title: str = ""
) -> dict[str, Any]:
    """Full step: register assets -> VLM analysis -> script draft (or pending)."""
    registered = register_assets(assets)
    result = analyze_assets(registered, vlm_fn=vlm_fn)
    draft = None
    if result["status"] == "ready":
        draft = draft_script(result["analysis"], title=title)
    return {
        "status": result["status"],
        "assets": registered,
        "analysis": result["analysis"],
        "draft": draft,
        "failures": result["failures"],
        "note": result["note"],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    # The render uses the module-level injected VLM (set_vlm_fn): JSON
    # params cannot carry a function, and no default VLM is ever used.
    payload = asset_script(
        params["assets"], vlm_fn=None, title=str(params.get("title", ""))
    )
    report = Path(out_dir) / "asset_script.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_asset_script_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.asset_script",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "assets": {"type": "array", "items": {"type": "object"}},
                    "title": {"type": "string"},
                },
                "required": ["assets"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "User-asset script draft: register the user's own photos "
                "or videos, analyse them with an injected VLM "
                "(set_vlm_fn; no default route, DashScope never used by "
                "default), and draft scenes + shot points from the "
                "analysis fields only. With no VLM, or on VLM failure, "
                "the result is honestly pending with draft=null -- "
                "never a fabricated analysis. Readable plan only: no "
                "video is rendered and no generation API is called."
            ),
            line="reference_bundle",
        )
    )
    return ["story.asset_script"]


register_asset_script_capabilities_once()
