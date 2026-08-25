from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from hevi.artifact_store import LocalObjectStore, expiry_for_role
from hevi.artifact_store.object_store import MinioObjectStore
from hevi.core.config import settings


def test_raw_attempts_expire_inside_thirty_to_ninety_days() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    expires = expiry_for_role("raw", now=now)
    assert expires is not None
    delta = expires - now
    assert timedelta(days=30) <= delta <= timedelta(days=90)
    assert settings.artifact_raw_retention_days == 60
    assert expiry_for_role("final", now=now) is None
    assert expiry_for_role("selected", now=now) is None


@pytest.mark.asyncio
async def test_local_object_store_delete_removes_bytes(tmp_path: Path) -> None:
    source = tmp_path / "raw.bin"
    source.write_bytes(b"raw-attempt")
    store = LocalObjectStore(tmp_path / "objects")
    stored = await store.put_file(source)
    await store.delete(stored.uri)
    with pytest.raises(FileNotFoundError):
        await store.get_bytes(stored.uri)


@pytest.mark.asyncio
async def test_minio_store_requires_matching_bucket() -> None:
    class _Client:
        pass

    store = MinioObjectStore(_Client(), bucket="hevi-assets")
    with pytest.raises(ValueError, match="does not belong"):
        await store.delete("s3://other/key")
