"""qwen_image_service 测试——2026-07-13 新增的多图融合支持(qwen-image-edit 官方
文档实测确认支持1-3张输入图,之前 hevi 只传过1张)。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.image.qwen_image_service import QwenImageError, qwen_image_edit


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    resp.content = b"fake-image-bytes" * 100  # >= 1024 bytes,_download 的最小落盘门槛
    return resp


def _fake_client(post_response: MagicMock, get_response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock(return_value=post_response)
    client.get = AsyncMock(return_value=get_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_multi_image_edit_sends_all_images_and_single_text(tmp_path, monkeypatch):
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")

    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    img1.write_bytes(b"fake-a")
    img2.write_bytes(b"fake-b")

    edit_response = _fake_response(
        {"output": {"choices": [{"message": {"content": [{"image": "https://x/y.png"}]}}]}}
    )
    download_response = _fake_response({})
    client = _fake_client(edit_response, download_response)

    with patch("httpx.AsyncClient", return_value=client):
        await qwen_image_edit(
            image_path=[img1, img2],
            instruction="合成到一张图",
            output_path=tmp_path / "out.png",
        )

    payload = client.post.await_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    # 2 张图 + 1 段文字,且文字段落只有一个(官方约束:仅支持传入一个 text)。
    image_parts = [c for c in content if "image" in c]
    text_parts = [c for c in content if "text" in c]
    assert len(image_parts) == 2
    assert len(text_parts) == 1


@pytest.mark.asyncio
async def test_single_image_edit_still_works_unchanged(tmp_path, monkeypatch):
    """向后兼容:原有单图调用方式(image_path=单个 Path)不受影响。"""
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")

    img = tmp_path / "a.png"
    img.write_bytes(b"fake-a")

    edit_response = _fake_response(
        {"output": {"choices": [{"message": {"content": [{"image": "https://x/y.png"}]}}]}}
    )
    download_response = _fake_response({})
    client = _fake_client(edit_response, download_response)

    with patch("httpx.AsyncClient", return_value=client):
        await qwen_image_edit(
            image_path=img, instruction="改表情", output_path=tmp_path / "out.png"
        )

    content = client.post.await_args.kwargs["json"]["input"]["messages"][0]["content"]
    assert len([c for c in content if "image" in c]) == 1


@pytest.mark.asyncio
async def test_more_than_three_images_rejected(tmp_path, monkeypatch):
    """qwen-image-edit 官方约束:最多支持3张输入图,超出应该在调用前拦下,而不是
    发一个注定失败的真实请求。"""
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")

    imgs = [tmp_path / f"{i}.png" for i in range(4)]
    for p in imgs:
        p.write_bytes(b"fake")

    with pytest.raises(QwenImageError, match="1-3"):
        await qwen_image_edit(image_path=imgs, instruction="x", output_path=tmp_path / "out.png")
