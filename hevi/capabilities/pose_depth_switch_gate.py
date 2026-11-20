"""Depth-map switch gate (``qa.pose_depth_switch_gate``).

White-model / depth-map switching for pose references from
anhao/ai-pose-gallery-zh: every pose view has a depth map
under ``img/depth/<record_id>.webp`` (1439 webp files, one
per pose-by-view record). The naming convention was verified
against the upstream tree listing on 2026-11-20
(``full_sexy_P001_front.webp`` and siblings share the white
model's record id stem, with the same five view suffixes).
The bundled ``pose_index.json`` carries a ``depth`` field on
every view entry derived from that convention; the field is
a path, never image bytes.

The gate validates a switch declaration and, by default,
checks the files on disk under ``HEVI_POSE_GALLERY_HOME``:
switching to depth when the depth file is absent fails by
name, and switching to white when the white file is absent
fails the same way. Nothing is faked: a missing gallery
directory fails, and ``pose_index_depth_coverage`` reports
how many bundled view entries actually carry a depth field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities import pose_library
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

MODES: frozenset[str] = frozenset({"white", "depth"})
DEPTH_DIR = "img/depth"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def depth_path_for(pose_key: str, view: str) -> str:
    """Derive the conventional depth path for one pose view.

    The depth file shares the white model's record id:
    ``img/depth/<record_id>.webp``. Raises CapabilityError on
    an unknown pose key or a view the pose does not have.
    """
    group = pose_library.get_pose_by_key(pose_key)
    entry = group["views"].get(view)
    if entry is None:
        raise CapabilityError(
            f"pose_depth_switch: pose {pose_key!r} has no {view!r} view "
            f"(missing views: {group['missing_views']})"
        )
    return f"{DEPTH_DIR}/{entry['id']}.webp"


def pose_index_depth_coverage() -> dict[str, Any]:
    """Report how many bundled view entries carry a depth field."""
    index = pose_library.load_index()
    total = 0
    with_depth = 0
    for group in index["groups"]:
        for view in pose_library.VIEWS:
            entry = group["views"].get(view)
            if entry is None:
                continue
            total += 1
            if entry.get("depth"):
                with_depth += 1
    return {
        "total_views": total,
        "depth_fields": with_depth,
        "naming_convention": f"{DEPTH_DIR}/<record_id>.webp",
        "convention_verified": "upstream tree listing 2026-11-20",
    }


def check_pose_depth_switch(decl: Any, *, check_disk: bool = True) -> dict[str, Any]:
    """Validate one white/depth switch declaration.

    Verdicts are ``pass`` / ``fail`` only. A declaration fails
    when the pose key or view is unknown, the mode is not white
    or depth, a supplied path does not match the indexed white
    path or the derived depth path, or (with ``check_disk``)
    the gallery directory or the file the mode needs is absent.
    With ``check_disk=False`` only the declaration shape and
    the path derivation are judged; the files are not touched.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(decl, dict):
        return fail("switch_not_object", "depth switch declaration must be a JSON object")
    pose_key = decl.get("pose_key")
    view = decl.get("view")
    mode = decl.get("mode")
    if not isinstance(pose_key, str) or not pose_key.strip():
        return fail("pose_key_missing", "depth switch must name a pose_key")
    if view not in pose_library.VIEWS:
        return fail(
            "unknown_view",
            f"view must be one of {list(pose_library.VIEWS)}, got {view!r}",
        )
    if mode not in MODES:
        return fail(
            "unknown_mode",
            f"mode must be one of {sorted(MODES)}, got {mode!r}",
        )
    try:
        group = pose_library.get_pose_by_key(pose_key)
    except CapabilityError as exc:
        return fail("unknown_pose_key", str(exc))
    entry = group["views"].get(view)
    if entry is None:
        return fail(
            "view_missing_for_pose",
            f"pose {pose_key!r} has no {view!r} view (missing views: {group['missing_views']})",
        )
    white_path = decl.get("white_path")
    if white_path is not None and white_path != entry["image"]:
        return fail(
            "white_path_mismatch",
            f"white path for {pose_key!r} {view!r} is {entry['image']!r}, got {white_path!r}",
        )
    derived_depth = f"{DEPTH_DIR}/{entry['id']}.webp"
    depth_path = decl.get("depth_path")
    if depth_path is not None and depth_path != derived_depth:
        return fail(
            "depth_path_mismatch",
            f"depth path for {pose_key!r} {view!r} is {derived_depth!r}, got {depth_path!r}",
        )
    if not check_disk:
        return {
            "verdict": "pass",
            "ok": True,
            "issues": [],
            "pose_key": pose_key,
            "view": view,
            "mode": mode,
            "white_path": entry["image"],
            "depth_path": derived_depth,
            "disk_checked": False,
            "executed_here": False,
        }
    home = pose_library.gallery_home(decl.get("home"))
    if not home.is_dir():
        return fail(
            "gallery_missing",
            f"gallery directory not found: {home} "
            "(set HEVI_POSE_GALLERY_HOME to a checkout of "
            "anhao/ai-pose-gallery-zh)",
        )
    white_file = home / entry["image"]
    depth_file = home / derived_depth
    white_exists = white_file.is_file()
    depth_exists = depth_file.is_file()
    if mode == "white" and not white_exists:
        return fail(
            "white_file_missing",
            f"white-model file missing on disk: {white_file}",
        )
    if mode == "depth" and not depth_exists:
        return fail(
            "depth_file_missing",
            f"depth-map file missing on disk: {depth_file}",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "pose_key": pose_key,
        "view": view,
        "mode": mode,
        "white_path": entry["image"],
        "depth_path": derived_depth,
        "white_exists": white_exists,
        "depth_exists": depth_exists,
        "disk_checked": True,
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_pose_depth_switch(params.get("switch"))
    report_path = out_dir / "pose_depth_switch_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_pose_depth_switch_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.pose_depth_switch_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "switch": {"type": "object"},
                },
                "required": ["switch"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Pose-gallery depth switch gate: white-model and "
                "depth-map paths derive from the bundled pose index, "
                "depth files live under img/depth/, a switch to a "
                "missing file fails by name, nothing is faked."
            ),
        )
    )
    return ["qa.pose_depth_switch_gate"]


__all__ = [
    "DEPTH_DIR",
    "MODES",
    "check_pose_depth_switch",
    "depth_path_for",
    "pose_index_depth_coverage",
    "register_pose_depth_switch_gate_capabilities_once",
]
