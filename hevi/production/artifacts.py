"""Stable artifact manifest for new production tasks.

Legacy tasks continue to use ``result_video_path``.  New writers may persist
this manifest in ``video_tasks.config_json``; readers always verify files at
download time so a completed state never masquerades as a deliverable.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
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

        return [item.artifact_id or item.path for item in self.artifacts if not item.integrity_ok()]

    @staticmethod
    def _resolve(artifact: Artifact | None) -> Path | None:
        if artifact is None:
            return None
        path = Path(artifact.path)
        return path if path.is_absolute() else (Path.cwd() / path).resolve()


class ArtifactVerificationError(RuntimeError):
    """Adapter claimed completion without a verified local artifact."""


def verify_production_artifact(
    path: str | Path,
    *,
    require_audio: bool = False,
    minimum_bytes: int = 1024,
    reject_fixture_names: bool = True,
) -> dict[str, Any]:
    """Canonical final-video truth gate, returning persisted evidence."""
    dest = Path(path)
    errors: list[str] = []
    if reject_fixture_names and any(token in dest.name.lower() for token in ("placeholder", "fixture", "test_artifact", "qualification")):
        errors.append("placeholder_or_qualification_name")
    if not dest.is_file():
        errors.append("path_missing")
    elif dest.stat().st_size <= minimum_bytes:
        errors.append("artifact_below_minimum_size")
    probe: dict[str, Any] = {"path": str(dest), "video_stream": False, "audio_stream": False}
    if not errors and shutil.which("ffprobe"):
        raw = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(dest)], capture_output=True, text=True, timeout=60, check=False)
        if raw.returncode != 0:
            errors.append("ffprobe_failed")
        else:
            try:
                payload = json.loads(raw.stdout)
                streams = payload.get("streams", [])
                video = next((s for s in streams if s.get("codec_type") == "video"), None)
                audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
                duration = float((payload.get("format") or {}).get("duration") or 0)
                fps_raw = str((video or {}).get("r_frame_rate", "0/1")).split("/")
                fps = float(fps_raw[0]) / float(fps_raw[1]) if len(fps_raw) == 2 and float(fps_raw[1]) else 0.0
                probe.update({"video_stream": video is not None, "audio_stream": audio is not None, "duration": duration, "width": (video or {}).get("width", 0), "height": (video or {}).get("height", 0), "fps": fps})
                if video is None: errors.append("video_stream_missing")
                if duration <= 0: errors.append("duration_not_positive")
                if not probe["width"] or not probe["height"] or probe["fps"] <= 0: errors.append("video_geometry_invalid")
                if require_audio and audio is None: errors.append("audio_stream_missing")
            except (ValueError, TypeError, json.JSONDecodeError):
                errors.append("ffprobe_invalid_json")
    elif not errors:
        errors.append("ffprobe_unavailable")
    digest = None
    if dest.is_file():
        h = hashlib.sha256()
        with dest.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
    return {"verified": not errors, "passed": not errors, "path": str(dest), "sha256": digest, "byte_size": dest.stat().st_size if dest.is_file() else 0, "errors": errors, "probe": probe}


def verify_local_manifest(
    manifest: ArtifactManifest,
    *,
    require_primary: bool = True,
    require_video_stream: bool = True,
) -> ArtifactManifest:
    """Normalize and verify a manifest before a task becomes completed.

    Adapters may return artifact metadata without integrity fields.  This
    boundary computes the hash, then requires every declared local file to
    exist and be non-empty.  Video artifacts additionally need a real ffprobe
    video stream; a JSON path or arbitrary non-empty file is not delivery.
    """

    if not manifest.artifacts:
        raise ArtifactVerificationError("artifact manifest is empty")
    if require_primary and not any(item.primary for item in manifest.artifacts):
        raise ArtifactVerificationError("artifact manifest has no primary artifact")
    has_video = any(item.kind == "video" for item in manifest.artifacts)
    if require_video_stream and has_video and not shutil.which("ffprobe"):
        raise ArtifactVerificationError("ffprobe is required to verify video delivery")

    normalized = manifest.model_copy(
        update={"artifacts": [item.with_integrity() for item in manifest.artifacts]}
    )
    failures: list[str] = []
    for item in normalized.artifacts:
        path = Path(item.path)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.is_file() or path.stat().st_size <= 0:
            failures.append(f"{item.kind}:{item.path}")
            continue
        if not item.sha256 or not item.byte_size or not item.integrity_ok():
            failures.append(f"integrity:{item.path}")

        if require_video_stream and item.kind == "video":
            from hevi.production.delivery_gate import probe_video

            probe = probe_video(path)
            if not probe.has_video:
                failures.append(f"video-stream:{item.path}")

    if failures:
        raise ArtifactVerificationError("; ".join(failures))
    return normalized


def manifest_from_task(task: dict[str, Any]) -> ArtifactManifest | None:
    raw = (task.get("config_json") or {}).get("artifact_manifest")
    if not raw:
        return None
    try:
        return ArtifactManifest.model_validate(raw)
    except Exception:
        return None
