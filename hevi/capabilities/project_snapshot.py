"""Project snapshots and conflict protection (``pipeline.project_snapshot``).

The anti-loss layer that ``pipeline.project_handoff`` does not have:

* Snapshots are manual. ``create_snapshot`` copies the current
  project manifest (plus a file inventory with sha256, so a restore
  can say exactly which files are gone instead of guessing) into
  ``<project>/snapshots/``. Retention is configurable with
  ``keep`` and defaults to the most recent 20 snapshots; older
  snapshot files are deleted on create.
* Restore backs up first. ``restore_snapshot`` always writes a fresh
  snapshot labelled ``pre-restore-backup`` before it touches the
  live manifest, then restores the requested snapshot's manifest and
  reports which inventoried files are no longer on disk. File
  contents are not duplicated by snapshots -- only the manifest
  state is restored, and the inventory gap is reported honestly.
* Old writes never silently overwrite new content. ``guarded_write``
  compares an incoming record's ``version`` and ``updated_at``
  against the live record's: an incoming version lower than live, or
  the same version with an older timestamp, is refused with both
  sides named. ``check_stale`` is the non-raising twin.
* Conflict stops auto-commit and keeps a local draft.
  ``save_with_conflict`` takes a local draft and the state it was
  based on plus the current live state: when both sides moved past
  the base (a real conflict), it writes the draft to
  ``<project>/drafts/`` and returns ``status: conflicted`` without
  touching the live manifest. When only one side moved, the draft
  applies cleanly and the result says so.
* Timed snapshots are a stub, stated as such.
  ``schedule_periodic_snapshot`` is an empty implementation: it
  returns ``scheduled: False`` and says plainly that no timer is
  connected and snapshots must be triggered manually with
  ``create_snapshot``. It schedules nothing, silently or otherwise.
"""

from __future__ import annotations

import json
import time
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

DEFAULT_KEEP = 20
SNAPSHOT_DIRNAME = "snapshots"
DRAFT_DIRNAME = "drafts"


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.project_snapshot: {message}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _snapshot_dir(project_root: Path) -> Path:
    return Path(project_root) / SNAPSHOT_DIRNAME


def list_snapshots(project_root: Path) -> list[dict[str, Any]]:
    """Snapshots newest first (by version, then filename)."""
    directory = _snapshot_dir(project_root)
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and "snapshot_id" in data:
            out.append({**data, "path": str(path)})
    out.sort(key=lambda d: (d.get("version", 0), d.get("snapshot_id", "")))
    return list(reversed(out))


def _next_version(project_root: Path) -> int:
    existing = list_snapshots(project_root)
    if not existing:
        return 1
    return max(int(s.get("version", 0)) for s in existing) + 1


def _inventory(project_root: Path) -> list[dict[str, Any]]:
    root = Path(project_root)
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(SNAPSHOT_DIRNAME + "/") or rel.startswith(
            DRAFT_DIRNAME + "/"
        ):
            continue
        try:
            digest = compute_sha256(path)
        except CapabilityError:
            digest = ""
        items.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": digest,
        })
    return items


def create_snapshot(
    project_root: Path,
    *,
    label: str = "",
    keep: int = DEFAULT_KEEP,
) -> dict[str, Any]:
    """Manually snapshot the current project state."""
    root = Path(project_root)
    if not root.is_dir():
        _fail(f"project root not found: {root}")
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 1:
        _fail(f"keep must be a whole number of at least 1; got {keep!r}")
    manifest_path = root / "manifest.json"
    manifest = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"manifest is not valid JSON: {manifest_path}")
    version = _next_version(root)
    snapshot_id = f"snap-{version:04d}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    payload = {
        "snapshot_id": snapshot_id,
        "label": label,
        "version": version,
        "created_at": _now_iso(),
        "manifest": manifest,
        "inventory": _inventory(root),
    }
    directory = _snapshot_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snapshot_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    pruned = prune_snapshots(root, keep=keep)
    return {
        "snapshot_id": snapshot_id,
        "version": version,
        "created_at": payload["created_at"],
        "label": label,
        "path": str(path),
        "pruned": pruned,
        "kept": keep,
    }


def prune_snapshots(project_root: Path, *, keep: int = DEFAULT_KEEP) -> list[str]:
    """Delete all but the newest ``keep`` snapshots; return pruned ids."""
    snaps = list_snapshots(project_root)
    if len(snaps) <= keep:
        return []
    pruned: list[str] = []
    for snap in snaps[keep:]:
        try:
            Path(snap["path"]).unlink()
            pruned.append(str(snap["snapshot_id"]))
        except OSError:
            continue
    return pruned


def restore_snapshot(
    project_root: Path, snapshot_id: str
) -> dict[str, Any]:
    """Back up current state, then restore a snapshot's manifest."""
    root = Path(project_root)
    if not root.is_dir():
        _fail(f"project root not found: {root}")
    snaps = {s["snapshot_id"]: s for s in list_snapshots(root)}
    if snapshot_id not in snaps:
        _fail(
            f"snapshot not found: {snapshot_id!r}; "
            f"known: {sorted(snaps)}"
        )
    backup = create_snapshot(root, label="pre-restore-backup")
    snap = snaps[snapshot_id]
    manifest = snap.get("manifest")
    restored_manifest = False
    if manifest is not None:
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        restored_manifest = True
    missing_files = [
        item["path"] for item in snap.get("inventory", [])
        if not (root / item["path"]).is_file()
    ]
    return {
        "restored_snapshot_id": snapshot_id,
        "backup_snapshot_id": backup["snapshot_id"],
        "backup_label": "pre-restore-backup",
        "restored_manifest": restored_manifest,
        "missing_files": missing_files,
        "note": (
            "Snapshots restore manifest state; file contents are not "
            "duplicated, so missing_files lists inventoried files that "
            "are no longer on disk instead of fabricating them."
        ),
    }


def check_stale(
    current_version: Any,
    current_updated_at: Any,
    incoming_version: Any,
    incoming_updated_at: Any,
) -> dict[str, Any]:
    """Is an incoming write older than the live record? Never raises."""
    try:
        cur_v = int(current_version)
        inc_v = int(incoming_version)
    except (TypeError, ValueError):
        return {
            "stale": True,
            "reason": (
                "version is missing or not a number on one side; "
                "an unversioned write is refused rather than allowed "
                "to silently overwrite"
            ),
        }
    cur_t = str(current_updated_at or "")
    inc_t = str(incoming_updated_at or "")
    if inc_v < cur_v:
        return {
            "stale": True,
            "reason": (
                f"incoming version {inc_v} is older than live "
                f"version {cur_v}; old write refused"
            ),
        }
    if inc_v == cur_v and inc_t and cur_t and inc_t < cur_t:
        return {
            "stale": True,
            "reason": (
                f"same version {cur_v} but incoming timestamp {inc_t} "
                f"is older than live timestamp {cur_t}; old write refused"
            ),
        }
    return {"stale": False, "reason": ""}


def guarded_write(
    state_path: Path,
    new_data: dict[str, Any],
) -> dict[str, Any]:
    """Write ``new_data`` only if it is not older than the live record.

    ``new_data`` must carry ``version`` (int) and ``updated_at``
    (ISO string). An older incoming record raises CapabilityError
    and the live file is left untouched.
    """
    path = Path(state_path)
    if not isinstance(new_data, dict):
        _fail("guarded_write: new_data must be an object")
    if "version" not in new_data or "updated_at" not in new_data:
        _fail(
            "guarded_write: new_data must carry version and updated_at; "
            "an unversioned write is refused"
        )
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"guarded_write: live record is not valid JSON: {path}")
        verdict = check_stale(
            current.get("version"), current.get("updated_at"),
            new_data.get("version"), new_data.get("updated_at"),
        )
        if verdict["stale"]:
            _fail(
                "guarded_write refused: old content must not silently "
                f"overwrite new content: {verdict['reason']} "
                f"(live file untouched: {path})"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new_data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {"written": str(path), "version": new_data["version"]}


def save_with_conflict(
    project_root: Path,
    local_draft: dict[str, Any],
    *,
    base_version: Any,
    live_version: Any,
    draft_version: Any,
) -> dict[str, Any]:
    """Save a draft under conflict rules; never auto-commit on conflict.

    Both sides moved past ``base_version`` -> conflict: the draft is
    written to ``<project>/drafts/``, the live manifest is untouched,
    and the result is ``status: conflicted``. Otherwise the draft
    applies cleanly (result says so, and the caller -- not this
    function -- decides whether to apply it).
    """
    root = Path(project_root)
    if not root.is_dir():
        _fail(f"project root not found: {root}")
    try:
        base = int(base_version)
        live = int(live_version)
        draft_v = int(draft_version)
    except (TypeError, ValueError):
        _fail("save_with_conflict: base/live/draft versions must be numbers")
    conflicted = live != base and draft_v != base and live != draft_v
    if not conflicted:
        return {
            "status": "clean",
            "conflicted": False,
            "draft_path": None,
            "note": "Only one side moved past the base; no conflict.",
        }
    directory = root / DRAFT_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    draft_id = f"draft-{_now_iso().replace(':', '').replace('-', '')}"
    path = directory / f"{draft_id}.json"
    payload = {
        "draft_id": draft_id,
        "status": "conflicted",
        "base_version": base,
        "live_version": live,
        "draft_version": draft_v,
        "draft": local_draft,
        "saved_at": _now_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return {
        "status": "conflicted",
        "conflicted": True,
        "draft_path": str(path),
        "draft_id": draft_id,
        "auto_commit": False,
        "note": (
            "Conflict: automatic commit stopped; local draft preserved "
            "on disk for manual resolution. Live state untouched."
        ),
    }


def schedule_periodic_snapshot(
    project_root: Path, *, interval_minutes: Any = None
) -> dict[str, Any]:
    """Stub: periodic snapshots are NOT connected to any timer.

    This is deliberately an empty implementation. It schedules
    nothing and must not be read as scheduling anything: snapshots
    are manual-only until a timer is wired up by a separate change.
    """
    return {
        "scheduled": False,
        "interval_minutes": interval_minutes,
        "project_root": str(project_root),
        "reason": (
            "定时器未接通：本接口为空实现，未接入任何定时器；"
            "快照只能手动触发 create_snapshot，定时快照不在本次交付内。"
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "snapshot")
    root = Path(params["project_root"])
    if action == "snapshot":
        result: dict[str, Any] = {
            "capability": "pipeline.project_snapshot",
            **create_snapshot(
                root, label=str(params.get("label", "")),
                keep=int(params.get("keep", DEFAULT_KEEP)),
            ),
        }
    elif action == "list":
        result = {
            "capability": "pipeline.project_snapshot",
            "snapshots": list_snapshots(root),
        }
    elif action == "restore":
        result = {
            "capability": "pipeline.project_snapshot",
            **restore_snapshot(root, str(params["snapshot_id"])),
        }
    elif action == "schedule":
        result = {
            "capability": "pipeline.project_snapshot",
            **schedule_periodic_snapshot(
                root, interval_minutes=params.get("interval_minutes")),
        }
    elif action == "conflict":
        result = {
            "capability": "pipeline.project_snapshot",
            **save_with_conflict(
                root, dict(params.get("draft", {})),
                base_version=params.get("base_version"),
                live_version=params.get("live_version"),
                draft_version=params.get("draft_version"),
            ),
        }
    else:
        _fail(
            f"unknown action {action!r}; known: snapshot, list, "
            "restore, schedule, conflict"
        )
    report_path = out_dir / "project_snapshot_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_project_snapshot_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.project_snapshot",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "project_root": {"type": "string"},
                    "action": {"type": "string", "enum": [
                        "snapshot", "list", "restore", "schedule",
                        "conflict"]},
                    "label": {"type": "string"},
                    "keep": {"type": "integer", "minimum": 1},
                    "snapshot_id": {"type": "string"},
                    "draft": {"type": "object"},
                    "base_version": {"type": "integer"},
                    "live_version": {"type": "integer"},
                    "draft_version": {"type": "integer"},
                    "interval_minutes": {"type": "integer"},
                },
                "required": ["project_root"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Project snapshots and conflict protection: manual "
                "snapshots with configurable retention (default newest "
                "20), restore that backs up current state first, "
                "guarded writes that refuse an older version/timestamp "
                "over newer content, conflict handling that stops "
                "auto-commit and preserves the local draft on disk as "
                "conflicted. Periodic scheduling is an unconnected stub "
                "and is reported as such."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.project_snapshot"]


register_project_snapshot_capabilities_once()
