"""Local-first NLE workspace metadata and non-destructive history."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.studio.timeline import Timeline

TRANSITIONS = ("cut", "dissolve", "wipe", "smash")
EFFECTS = ("none", "warm", "cool", "mono", "vignette", "sharpen")


@dataclass
class NLEProject:
    project_id: str
    name: str
    timeline_ids: list[str] = field(default_factory=list)
    active_timeline_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "timeline_ids": list(self.timeline_ids),
            "active_timeline_id": self.active_timeline_id,
            "created_at": self.created_at,
            "version": self.version,
            "transitions": list(TRANSITIONS),
            "effects": list(EFFECTS),
            "local_first": True,
        }


_PROJECTS: dict[str, NLEProject] = {}
_HISTORY: dict[str, list[dict[str, Any]]] = {}


def _workspace_root() -> Path:
    return Path(os.getenv("HEVI_NLE_DIR", "data/nle")).expanduser()


def _project_path(project_id: str) -> Path:
    return _workspace_root() / f"{project_id}.json"


def _persist_project(project: NLEProject) -> None:
    root = _workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    body = {**project.to_dict(), "history": _HISTORY.get(project.project_id, [])}
    path = _project_path(project.project_id)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_project(project_id: str) -> NLEProject | None:
    path = _project_path(project_id)
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(body, dict):
            return None
        project = NLEProject(
            project_id=str(body.get("project_id") or project_id),
            name=str(body.get("name") or "untitled"),
            timeline_ids=[str(item) for item in body.get("timeline_ids") or []],
            active_timeline_id=str(body["active_timeline_id"])
            if body.get("active_timeline_id")
            else None,
            created_at=str(body.get("created_at") or datetime.now(UTC).isoformat()),
            version=int(body.get("version") or 1),
        )
        history = body.get("history") or []
        _HISTORY[project.project_id] = [item for item in history if isinstance(item, dict)]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    _PROJECTS[project.project_id] = project
    return project


def create_project(name: str, timeline: Timeline | None = None) -> NLEProject:
    project = NLEProject(project_id=str(uuid.uuid4()), name=name.strip() or "untitled")
    if timeline is not None:
        project.timeline_ids.append(timeline.timeline_id)
        project.active_timeline_id = timeline.timeline_id
    _PROJECTS[project.project_id] = project
    _HISTORY[project.project_id] = []
    _persist_project(project)
    return project


def list_projects() -> list[NLEProject]:
    root = _workspace_root()
    if root.is_dir():
        for path in root.glob("*.json"):
            if path.stem not in _PROJECTS:
                _load_project(path.stem)
    return list(_PROJECTS.values())


def get_project(project_id: str) -> NLEProject | None:
    return _PROJECTS.get(project_id) or _load_project(project_id)


def attach_timeline(project_id: str, timeline_id: str) -> NLEProject | None:
    project = get_project(project_id)
    if project is None:
        return None
    if timeline_id not in project.timeline_ids:
        project.timeline_ids.append(timeline_id)
    project.active_timeline_id = timeline_id
    project.version += 1
    _persist_project(project)
    return project


def record_revision(project_id: str, timeline: Timeline) -> None:
    project = get_project(project_id)
    if project is None:
        return
    _HISTORY.setdefault(project_id, []).append(timeline.to_dict())
    project.version += 1
    _persist_project(project)


def revisions(project_id: str) -> list[dict[str, Any]]:
    if project_id not in _HISTORY:
        _load_project(project_id)
    return list(_HISTORY.get(project_id, []))


def reset_projects() -> None:
    _PROJECTS.clear()
    _HISTORY.clear()


__all__ = [
    "EFFECTS",
    "TRANSITIONS",
    "NLEProject",
    "attach_timeline",
    "create_project",
    "get_project",
    "list_projects",
    "record_revision",
    "reset_projects",
    "revisions",
]
