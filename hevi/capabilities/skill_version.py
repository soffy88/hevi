"""Skill version management (``pipeline.skill_version``).

Method borrowed from the BeefTV skill-market shape (fixed-version
install, rollback to a previous version, private copy), rewritten
from scratch for hevi; see PRODUCTIZATION_ATTRIBUTION.md. No
upstream text is used here.

Rules enforced by this module:

* Fixed-version install. ``install_skill`` records exactly one
  version as current, together with who installed it, when, and
  where it came from (``source`` is a caller-supplied label, never
  fetched by this module). Installing a new version does not
  delete the old one: the old version becomes the rollback point.
* One-step rollback. ``rollback_skill`` restores the rollback
  point and consumes it, so a rollback is always to the version
  installed immediately before the current one. A rollback that
  cannot be completed leaves the current version untouched: the
  checks (known skill, rollback point present, rollback payload
  present and versioned) all run before anything is written, and
  a failure raises naming the reason.
* Private rewrites stay private. ``fork_private`` copies the
  current mainline payload into a separate private record. The
  mainline record is never written by a fork, and a later
  mainline install never touches private records, so a private
  rewrite is neither polluted by the mainline nor overwritten
  by its updates. Private records live under a separate
  ``private`` block, never under the mainline skill id.
* Version history. Every install, rollback and fork appends one
  history entry with actor, timestamp, from-version, to-version
  and the rollback point that results from the operation, so the
  full chain (including consumed rollback points) stays auditable
  after the point itself is gone.

Records live in one JSON file chosen by the caller. Payloads are
opaque to this module: it stores, copies and restores them
verbatim and never executes them.
"""

from __future__ import annotations

import copy
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


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.skill_version: {message}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _actor(actor: str | None) -> str:
    cleaned = (actor or "").strip()
    return cleaned if cleaned else "unknown"


def _load(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            _fail(f"skill store is not valid JSON: {path}")
        if not isinstance(data, dict) or "skills" not in data:
            _fail(f"skill store has no skills block: {path}")
        data.setdefault("private", {})
        data.setdefault("history", [])
        return data
    return {"capability": "pipeline.skill_version", "skills": {},
            "private": {}, "history": []}


def _save(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _check_id(skill_id: str) -> None:
    if not skill_id or not isinstance(skill_id, str):
        _fail("skill_id must be a non-empty string")


def install_skill(
    store_path: Path,
    *,
    skill_id: str,
    version: str,
    payload: Any,
    actor: str | None = None,
    source: str = "",
) -> dict[str, Any]:
    """Install ``version`` as current; the old version becomes the
    rollback point. Private records are never touched here."""
    _check_id(skill_id)
    if not version or not isinstance(version, str):
        _fail("install_skill: version must be a non-empty string")
    path = Path(store_path)
    data = _load(path)
    previous = data["skills"].get(skill_id)
    from_version = previous["version"] if previous else None
    rollback_point = None
    if previous is not None:
        rollback_point = {"version": previous["version"],
                          "payload": copy.deepcopy(previous["payload"])}
    record = {
        "skill_id": skill_id,
        "version": version,
        "payload": copy.deepcopy(payload),
        "installed_at": _now_iso(),
        "installed_by": _actor(actor),
        "source": source,
        "rollback_point": rollback_point,
    }
    data["skills"][skill_id] = record
    data["history"].append({
        "skill_id": skill_id,
        "kind": "install",
        "actor": _actor(actor),
        "at": record["installed_at"],
        "from_version": from_version,
        "to_version": version,
        "rollback_point_after": rollback_point["version"]
        if rollback_point else None,
    })
    _save(path, data)
    return copy.deepcopy(record)


def rollback_skill(
    store_path: Path, *, skill_id: str, actor: str | None = None
) -> dict[str, Any]:
    """Restore the rollback point and consume it.

    Every failure path raises before any write, so the current
    version, payload and rollback point stay exactly as they were.
    """
    _check_id(skill_id)
    path = Path(store_path)
    data = _load(path)
    record = data["skills"].get(skill_id)
    if record is None:
        _fail(f"unknown skill: {skill_id!r}; nothing rolled back")
    point = record.get("rollback_point")
    if point is None:
        _fail(
            f"skill {skill_id!r} has no rollback point "
            f"(current version {record.get('version')!r} stays unchanged); "
            f"install a newer version first to create one"
        )
    if not isinstance(point, dict) or not point.get("version"):
        _fail(
            f"skill {skill_id!r} rollback point is corrupt "
            f"(no version recorded); current version "
            f"{record.get('version')!r} stays unchanged"
        )
    if "payload" not in point or point["payload"] is None:
        _fail(
            f"skill {skill_id!r} rollback point payload is missing; "
            f"current version {record.get('version')!r} stays unchanged"
        )
    from_version = record["version"]
    at = _now_iso()
    record["version"] = point["version"]
    record["payload"] = copy.deepcopy(point["payload"])
    record["installed_at"] = at
    record["installed_by"] = _actor(actor)
    record["rollback_point"] = None
    data["history"].append({
        "skill_id": skill_id,
        "kind": "rollback",
        "actor": _actor(actor),
        "at": at,
        "from_version": from_version,
        "to_version": point["version"],
        "rollback_point_after": None,
    })
    _save(path, data)
    return copy.deepcopy(record)


def fork_private(
    store_path: Path,
    *,
    skill_id: str,
    private_id: str,
    actor: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy the current mainline payload into a private record.

    The mainline record is read, never written, by this function.
    ``overrides`` (when given) merge into a dict payload only; a
    non-dict payload with overrides is refused rather than
    silently merged.
    """
    _check_id(skill_id)
    if not private_id or not isinstance(private_id, str):
        _fail("fork_private: private_id must be a non-empty string")
    path = Path(store_path)
    data = _load(path)
    record = data["skills"].get(skill_id)
    if record is None:
        _fail(f"cannot fork unknown skill: {skill_id!r}")
    payload = copy.deepcopy(record["payload"])
    if overrides is not None:
        if not isinstance(payload, dict) or not isinstance(overrides, dict):
            _fail(
                "fork_private: overrides need a dict payload and a "
                "dict overrides mapping"
            )
        payload.update(copy.deepcopy(overrides))
    private = {
        "private_id": private_id,
        "base_skill_id": skill_id,
        "base_version": record["version"],
        "payload": payload,
        "forked_at": _now_iso(),
        "forked_by": _actor(actor),
        "private": True,
    }
    data["private"][private_id] = private
    data["history"].append({
        "skill_id": skill_id,
        "kind": "fork_private",
        "actor": _actor(actor),
        "at": private["forked_at"],
        "from_version": record["version"],
        "to_version": record["version"],
        "rollback_point_after": (
            record["rollback_point"]["version"]
            if record.get("rollback_point") else None
        ),
        "private_id": private_id,
    })
    _save(path, data)
    return copy.deepcopy(private)


def get_skill(store_path: Path, skill_id: str) -> dict[str, Any]:
    data = _load(Path(store_path))
    record = data["skills"].get(skill_id)
    if record is None:
        _fail(f"unknown skill: {skill_id!r}")
    return copy.deepcopy(record)


def get_private(store_path: Path, private_id: str) -> dict[str, Any]:
    data = _load(Path(store_path))
    record = data["private"].get(private_id)
    if record is None:
        _fail(f"unknown private rewrite: {private_id!r}")
    return copy.deepcopy(record)


def version_history(
    store_path: Path, skill_id: str | None = None
) -> list[dict[str, Any]]:
    data = _load(Path(store_path))
    entries = data["history"]
    if skill_id is not None:
        entries = [e for e in entries if e.get("skill_id") == skill_id]
    return copy.deepcopy(entries)


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    store = Path(params["store_path"])
    action = params.get("action", "get")
    if action == "install":
        result: dict[str, Any] = {
            "capability": "pipeline.skill_version",
            "record": install_skill(
                store, skill_id=str(params["skill_id"]),
                version=str(params["version"]),
                payload=params.get("payload"),
                actor=params.get("actor"),
                source=str(params.get("source", "")),
            ),
        }
    elif action == "rollback":
        result = {
            "capability": "pipeline.skill_version",
            "record": rollback_skill(
                store, skill_id=str(params["skill_id"]),
                actor=params.get("actor"),
            ),
        }
    elif action == "fork":
        result = {
            "capability": "pipeline.skill_version",
            "record": fork_private(
                store, skill_id=str(params["skill_id"]),
                private_id=str(params["private_id"]),
                actor=params.get("actor"),
                overrides=params.get("overrides"),
            ),
        }
    elif action == "history":
        result = {
            "capability": "pipeline.skill_version",
            "history": version_history(
                store, params.get("skill_id")),
        }
    elif action == "get":
        result = {
            "capability": "pipeline.skill_version",
            "record": get_skill(store, str(params["skill_id"])),
        }
    else:
        _fail(f"unknown action {action!r}; known: install, rollback, "
              f"fork, history, get")
    report_path = out_dir / "skill_version_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_skill_version_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.skill_version",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "store_path": {"type": "string"},
                    "action": {"type": "string", "enum": [
                        "install", "rollback", "fork", "history", "get"]},
                    "skill_id": {"type": "string"},
                    "version": {"type": "string"},
                    "payload": {},
                    "actor": {"type": "string"},
                    "source": {"type": "string"},
                    "private_id": {"type": "string"},
                    "overrides": {"type": "object"},
                },
                "required": ["store_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Skill version management: fixed-version install with "
                "actor, timestamp, source and from/to versions on "
                "record; one-step rollback to the previous version "
                "that leaves the current version untouched when it "
                "fails; private rewrites stored separately from the "
                "mainline so mainline updates never overwrite them "
                "and forks never pollute the mainline; full version "
                "history retained. Payloads are stored verbatim and "
                "never executed."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.skill_version"]


register_skill_version_capabilities_once()
