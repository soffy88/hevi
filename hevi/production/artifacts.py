"""Stable artifact manifest for new production tasks.

Legacy tasks continue to use ``result_video_path``.  New writers may persist
this manifest in ``video_tasks.config_json``; readers always verify files at
download time so a completed state never masquerades as a deliverable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    kind: str
    path: str
    media_type: str | None = None
    primary: bool = False
    artifact_id: str | None = None
    uri: str | None = None
    sha256: str | None = None
    byte_size: int | None = None
    logical_role: str | None = None
    created_by_attempt_id: str | None = None
    parent_artifact_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        kind: str,
        media_type: str | None = None,
        primary: bool = False,
        logical_role: str | None = None,
        **kwargs: Any,
    ) -> Artifact:
        artifact = cls(
            kind=kind,
            path=str(path),
            media_type=media_type,
            primary=primary,
            logical_role=logical_role,
            uri=kwargs.pop("uri", str(path)),
            **kwargs,
        )
        return artifact.with_integrity()

    def with_integrity(self) -> Artifact:
        """Return a copy with a content hash when the local file exists."""

        file_path = Path(self.path)
        if not file_path.is_file():
            return self
        digest = hashlib.sha256()
        byte_size = 0
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_size += len(chunk)
        return self.model_copy(update={"sha256": digest.hexdigest(), "byte_size": byte_size})

    def integrity_ok(self) -> bool:
        """Verify a recorded hash; missing local files are not silently valid."""

        if not self.sha256:
            return False
        return self.with_integrity().sha256 == self.sha256


class ArtifactManifest(BaseModel):
    version: int = 1
    production_id: str | None = None
    revision_id: str | None = None
    attempt_id: str | None = None
    tenant_id: str | None = None
    artifacts: list[Artifact] = Field(default_factory=list)

    @classmethod
    def for_video(cls, path: str | Path) -> ArtifactManifest:
        return cls(
            artifacts=[
                Artifact.from_path(
                    path,
                    kind="video",
                    media_type="video/mp4",
                    primary=True,
                    logical_role="final_video",
                )
            ]
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

    def verify_integrity(self) -> list[str]:
        """Return artifact ids/paths that cannot be verified locally."""

        return [
            item.artifact_id or item.path
            for item in self.artifacts
            if not item.integrity_ok()
        ]

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
