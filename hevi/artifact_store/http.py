"""HTTP delivery helpers for canonical artifact manifests."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from hevi.core.config import settings
from hevi.production.artifacts import Artifact, ArtifactManifest

from .factory import get_object_store


def _select(
    manifest: ArtifactManifest, kind: str, *, preferred_artifact_id: str | None = None
) -> Artifact:
    if preferred_artifact_id is not None:
        for item in manifest.artifacts:
            if (item.artifact_id or item.path) == preferred_artifact_id and (
                not kind or item.kind == kind
            ):
                return item
    artifact = next(
        (item for item in manifest.artifacts if item.kind == kind and item.primary),
        next((item for item in manifest.artifacts if item.kind == kind), None),
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail=f"{kind} artifact not found")
    return artifact


async def materialize_artifact(
    manifest: ArtifactManifest, *, kind: str, preferred_artifact_id: str | None = None
) -> Path:
    """Resolve an artifact through the object store and verify its digest."""

    artifact = _select(manifest, kind, preferred_artifact_id=preferred_artifact_id)
    uri = str(artifact.uri or "")
    if not uri:
        # Legacy/local manifests predate the object-store contract. They are
        # usable only in an explicitly local/debug process; production
        # writers are rejected by ArtifactRepository before completion.
        if (settings.local_mode or settings.debug) and Path(artifact.path).is_file():
            return _verify(Path(artifact.path), artifact.sha256)
        raise HTTPException(status_code=409, detail="artifact has no durable URI")

    if uri.startswith("file://"):
        path = Path(uri.removeprefix("file://"))
        if not path.is_file():
            raise HTTPException(status_code=404, detail="artifact object missing")
        return _verify(path, artifact.sha256)

    if uri.startswith("s3://"):
        try:
            payload = await get_object_store().get_bytes(uri)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="artifact object missing") from exc
        if artifact.sha256:
            digest = hashlib.sha256(payload).hexdigest()
            if digest != artifact.sha256:
                raise HTTPException(
                    status_code=409, detail="artifact integrity verification failed"
                )
        root = Path(tempfile.gettempdir()) / "hevi-artifact-cache"
        root.mkdir(parents=True, exist_ok=True)
        suffix = ".mp4" if kind == "video" else ".bin"
        path = root / f"{artifact.sha256 or hashlib.sha256(payload).hexdigest()}{suffix}"
        if not path.exists():
            path.write_bytes(payload)
        return path

    # Local compatibility manifests from pre-object-store tasks are accepted
    # only when the referenced worker file still exists.  Production writers
    # always produce file:// or s3:// URIs before marking a task complete.
    path = Path(uri)
    if path.is_file():
        return _verify(path, artifact.sha256)
    raise HTTPException(status_code=409, detail="artifact URI is not a supported object URI")


def preferred_ids_for_serving(
    task: dict[str, Any], manifest: ArtifactManifest
) -> tuple[str | None, str | None]:
    """Serve selection delegates to the Presentation Read Model (W10).

    Returns (video_id, audio_id) from the canonical snapshot when the
    manifest materializes with probed real durations; (None, None) when
    anything is unprovable, preserving the legacy primary-first fallback.
    The fallback only triggers on refusal — never on a second opinion.
    """
    try:
        from hevi.creative.layer4.presentation import for_download, snapshot_for_serving
        from hevi.production.delivery_gate import probe_manifest_durations_ms

        view = for_download(
            snapshot_for_serving(
                manifest, task=task, probe_durations_ms=probe_manifest_durations_ms(manifest)
            )
        )
        video_id = view["video_artifact_id"]
        return str(video_id), (
            str(view["audio_artifact_id"]) if view["audio_artifact_id"] else None
        )
    except Exception:
        return None, None


async def artifact_delivery_url(
    manifest: ArtifactManifest, *, kind: str, expires_s: int = 300
) -> str | None:
    """Return a short-lived object-store URL for browser-native delivery.

    Local mode deliberately returns ``None`` so callers fall back to the
    authenticated API stream.  Production MinIO delivery never requires the
    API process to materialize the complete video in its own filesystem.
    """

    artifact = _select(manifest, kind)
    uri = str(artifact.uri or "")
    if not uri.startswith("s3://"):
        return None
    try:
        return await get_object_store().presign_get(uri, expires_s=expires_s)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="artifact delivery unavailable") from exc


def _verify(path: Path, expected_sha256: str | None) -> Path:
    if expected_sha256:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise HTTPException(status_code=409, detail="artifact integrity verification failed")
    return path


async def artifact_file_response(
    manifest: ArtifactManifest, *, kind: str, filename: str, media_type: str
) -> FileResponse:
    path = await materialize_artifact(manifest, kind=kind)
    return FileResponse(str(path), media_type=media_type, filename=filename)


__all__ = ["artifact_delivery_url", "artifact_file_response", "materialize_artifact"]
