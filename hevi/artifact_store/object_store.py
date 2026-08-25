"""Content-addressed object-store boundary for artifacts.

Workers may use local scratch paths, but the persisted reference is an object
URI plus hash.  The MinIO adapter is intentionally dependency-light and wraps
its synchronous client behind a small adapter so storage semantics stay
independent from the production graph.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol, cast


@dataclass(frozen=True)
class StoredObject:
    uri: str
    sha256: str
    byte_size: int
    media_type: str | None = None


class ObjectStore(Protocol):
    async def put_file(
        self,
        path: str | Path,
        *,
        media_type: str | None = None,
        key_prefix: str | None = None,
    ) -> StoredObject:
        """Store a file and return its durable content-addressed reference."""

    async def get_bytes(self, uri: str) -> bytes:
        """Read an object by URI."""

    async def presign_get(self, uri: str, *, expires_s: int = 300) -> str | None:
        """Return a short-lived browser-download URL when the backend supports it."""

    async def delete(self, uri: str) -> None:
        """Remove a stored object. Missing objects are not an error."""


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_size += len(chunk)
    return digest.hexdigest(), byte_size


class LocalObjectStore:
    """Filesystem implementation for local mode and deterministic tests."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    async def put_file(
        self,
        path: str | Path,
        *,
        media_type: str | None = None,
        key_prefix: str | None = None,
    ) -> StoredObject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        sha256, byte_size = _digest(source)
        destination = self.root / sha256[:2] / sha256
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(source, destination)
        return StoredObject(
            uri=f"file://{destination.resolve()}",
            sha256=sha256,
            byte_size=byte_size,
            media_type=media_type,
        )

    async def get_bytes(self, uri: str) -> bytes:
        path = Path(uri.removeprefix("file://"))
        return path.read_bytes()

    async def presign_get(self, uri: str, *, expires_s: int = 300) -> str | None:
        # Local files are intentionally served through the authenticated API
        # route; exposing a filesystem path is neither portable nor safe.
        return None

    async def delete(self, uri: str) -> None:
        path = Path(uri.removeprefix("file://"))
        if path.is_file():
            path.unlink()


class MinioObjectStore:
    """Async façade over an injected synchronous MinIO-compatible client."""

    def __init__(self, client: Any, *, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    async def put_file(
        self,
        path: str | Path,
        *,
        media_type: str | None = None,
        key_prefix: str | None = None,
    ) -> StoredObject:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        data = source.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()

        object_key = "/".join(
            part.strip("/") for part in (key_prefix or "", sha256) if part.strip("/")
        )

        def _put() -> None:
            from io import BytesIO

            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            try:
                self.client.stat_object(self.bucket, object_key)
            except Exception:
                self.client.put_object(
                    self.bucket,
                    object_key,
                    BytesIO(data),
                    length=len(data),
                    content_type=media_type or "application/octet-stream",
                )

        _put()
        return StoredObject(
            uri=f"s3://{self.bucket}/{object_key}",
            sha256=sha256,
            byte_size=len(data),
            media_type=media_type,
        )

    async def get_bytes(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI does not belong to bucket {self.bucket!r}: {uri}")
        digest = uri.removeprefix(prefix)
        return cast(bytes, self.client.get_object(self.bucket, digest).read())

    async def presign_get(self, uri: str, *, expires_s: int = 300) -> str | None:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI does not belong to bucket {self.bucket!r}: {uri}")
        digest = uri.removeprefix(prefix)
        return cast(str | None, self.client.presigned_get_object(
            self.bucket,
            digest,
            expires=timedelta(seconds=max(1, expires_s)),
        ))

    async def delete(self, uri: str) -> None:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError(f"URI does not belong to bucket {self.bucket!r}: {uri}")
        digest = uri.removeprefix(prefix)

        def _delete() -> None:
            try:
                self.client.remove_object(self.bucket, digest)
            except Exception as exc:
                missing = getattr(exc, "code", "") in {"NoSuchKey", "NoSuchObject"}
                if not missing:
                    raise

        _delete()


__all__ = ["LocalObjectStore", "MinioObjectStore", "ObjectStore", "StoredObject"]
