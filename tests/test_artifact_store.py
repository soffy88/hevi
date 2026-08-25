import pytest

from hevi.artifact_store import LocalObjectStore


@pytest.mark.asyncio
async def test_local_object_store_is_content_addressed_and_deduplicated(tmp_path) -> None:
    source = tmp_path / "render.mp4"
    source.write_bytes(b"same-content")
    store = LocalObjectStore(tmp_path / "objects")

    first = await store.put_file(source, media_type="video/mp4")
    second = await store.put_file(source, media_type="video/mp4")

    assert first == second
    assert first.uri.startswith("file://")
    assert first.byte_size == len(b"same-content")
    assert await store.get_bytes(first.uri) == b"same-content"
    assert await store.presign_get(first.uri) is None
