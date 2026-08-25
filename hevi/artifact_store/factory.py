"""Composition root for the authoritative artifact object store."""

from __future__ import annotations

from functools import lru_cache

from hevi.core.config import settings

from .object_store import LocalObjectStore, MinioObjectStore, ObjectStore


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    """Return the only object-store implementation allowed by the runtime mode."""

    if settings.local_mode:
        return LocalObjectStore(settings.artifact_local_root)
    if not settings.minio_access_key or not settings.minio_secret_key:
        raise RuntimeError(
            "MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required in PostgreSQL production mode"
        )
    from minio import Minio

    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    return MinioObjectStore(client, bucket=settings.minio_bucket)


__all__ = ["get_object_store"]
