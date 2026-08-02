"""Stable artifact manifest for new production tasks.

Legacy tasks continue to use ``result_video_path``.  New writers may persist
this manifest in ``video_tasks.config_json``; readers always verify files at
download time so a completed state never masquerades as a deliverable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    kind: str
    path: str
    media_type: str | None = None
    primary: bool = False


class ArtifactManifest(BaseModel):
    version: int = 1
    artifacts: list[Artifact] = Field(default_factory=list)

    @classmethod
    def for_video(cls, path: str | Path) -> ArtifactManifest:
        return cls(
            artifacts=[Artifact(kind="video", path=str(path), media_type="video/mp4", primary=True)]
        )

    def primary_path(self) -> Path | None:
        artifact = next((item for item in self.artifacts if item.primary), None)
        return self._resolve(artifact)

    def path_for(self, kind: str) -> Path | None:
        artifact = next(
            (item for item in self.artifacts if item.kind == kind and item.primary),
            next((item for item in self.artifacts if item.kind == kind), None),
        )
        return self._resolve(artifact)

    @staticmethod
    def _resolve(artifact: Artifact | None) -> Path | None:
        if artifact is None:
            return None
        path = Path(artifact.path)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()


def manifest_from_task(task: dict[str, Any]) -> ArtifactManifest | None:
    raw = (task.get("config_json") or {}).get("artifact_manifest")
    if not raw:
        return None
    try:
        return ArtifactManifest.model_validate(raw)
    except Exception:
        return None
