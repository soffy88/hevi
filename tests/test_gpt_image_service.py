"""Offline contract tests for the GPT-Image cloud image service (via Monid)."""

from pathlib import Path

import pytest

from hevi.audio import monid_client
from hevi.image import gpt_image_service


def _write_png(path: Path, payload: bytes = b"fakepng") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


@pytest.mark.asyncio
async def test_gpt_image_generate_saves_downloaded_png(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "gen.png"
    seen: dict[str, object] = {}

    async def fake_run(provider: str, endpoint: str, **kwargs):
        seen.update(provider=provider, endpoint=endpoint, body=kwargs.get("body"))
        return {"image": {"download_link": "https://example.test/img.png"}}, 0.0107

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"png-bytes"

    monkeypatch.setattr(monid_client, "run_endpoint", fake_run)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=180: _Resp()
    )

    result = await gpt_image_service.gpt_image_generate(
        prompt="a studio host", output_path=out, size="1024x1536", quality="medium"
    )
    assert result["output_path"] == str(out)
    assert result["cost"] == 0.0107
    assert out.read_bytes() == b"png-bytes"
    body = seen["body"]
    assert body["prompt"] == "a studio host"
    assert body["size"] == "1024x1536"


@pytest.mark.asyncio
async def test_gpt_image_edit_uploads_references_and_uses_edit_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ref = tmp_path / "ref.png"
    _write_png(ref)
    out = tmp_path / "edit.png"
    seen: dict[str, object] = {}

    async def fake_upload(local_path: Path, *, sfs_path: str, ttl: str = "1d") -> str:
        seen["ref_uploaded"] = str(local_path)
        return "https://example.test/ref.png"

    async def fake_run(provider: str, endpoint: str, **kwargs):
        seen.update(provider=provider, endpoint=endpoint, body=kwargs.get("body"))
        return {"image": {"download_link": "https://example.test/edited.png"}}, 0.023

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"edited-png"

    monkeypatch.setattr(monid_client, "sfs_upload_file", fake_upload)
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run)
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=180: _Resp()
    )

    result = await gpt_image_service.gpt_image_edit(
        image_paths=[ref],
        prompt="side profile, same man",
        output_path=out,
    )
    assert result["output_path"] == str(out)
    assert out.read_bytes() == b"edited-png"
    assert seen["endpoint"] == "/v1/image/gpt-image-2.5-sunburst-edit"
    assert seen["body"]["images"] == ["https://example.test/ref.png"]
    assert seen["ref_uploaded"] == str(ref)


@pytest.mark.asyncio
async def test_gpt_image_edit_rejects_empty_and_too_many_references(
    tmp_path: Path,
) -> None:
    with pytest.raises(monid_client.MonidError):
        await gpt_image_service.gpt_image_edit(
            image_paths=[], prompt="x", output_path=tmp_path / "o.png"
        )
    with pytest.raises(monid_client.MonidError):
        await gpt_image_service.gpt_image_edit(
            image_paths=[tmp_path / f"r{i}.png" for i in range(17)],
            prompt="x",
            output_path=tmp_path / "o.png",
        )
