"""qwen_image_service 测试——2026-07-13 新增的多图融合支持(qwen-image-edit 官方
文档实测确认支持1-3张输入图,之前 hevi 只传过1张)。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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
async def test_edit_retries_on_transient_403_then_succeeds(tmp_path, monkeypatch):
    """MaaS 端点整集逐镜高频出关键帧会间歇 403 限流,几十秒自恢复。提交要指数退避重试,
    不能一次 403 就抛(否则 scene_render_avatar 整镜降级空镜,用户实测"8 镜只出 1 镜")。"""
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")
    monkeypatch.setattr("hevi.image.qwen_image_service.asyncio.sleep", AsyncMock())  # 不真等退避

    img = tmp_path / "a.png"
    img.write_bytes(b"fake-a")

    forbidden = MagicMock()
    forbidden.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())
    )
    ok = _fake_response(
        {"output": {"choices": [{"message": {"content": [{"image": "https://x/y.png"}]}}]}}
    )
    download_response = _fake_response({})
    client = _fake_client(ok, download_response)
    # 前两次提交 403,第三次成功 → 应重试到成功,不抛
    client.post = AsyncMock(side_effect=[forbidden, forbidden, ok])

    with patch("httpx.AsyncClient", return_value=client):
        await qwen_image_edit(
            image_path=img, instruction="改表情", output_path=tmp_path / "out.png"
        )
    assert client.post.await_count == 3


@pytest.mark.asyncio
async def test_edit_fails_fast_on_free_tier_quota_wall(tmp_path, monkeypatch):
    """额度耗尽的 403(AllocationQuota.FreeTierOnly)不是瞬时限流,退避永远治不好。
    必须**一次就抛**清晰错误(别每镜傻等 78s×N),提示去控制台关「仅免费额度」。"""
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")
    sleep = AsyncMock()
    monkeypatch.setattr("hevi.image.qwen_image_service.asyncio.sleep", sleep)

    img = tmp_path / "a.png"
    img.write_bytes(b"fake-a")

    quota_resp = MagicMock()
    quota_resp.status_code = 403
    quota_resp.text = '{"code":"AllocationQuota.FreeTierOnly","message":"free quota exhausted"}'
    forbidden = MagicMock()
    forbidden.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=quota_resp)
    )
    client = _fake_client(forbidden, _fake_response({}))
    client.post = AsyncMock(return_value=forbidden)

    with patch("httpx.AsyncClient", return_value=client):
        with pytest.raises(QwenImageError, match="仅使用免费额度"):
            await qwen_image_edit(image_path=img, instruction="x", output_path=tmp_path / "out.png")
    assert client.post.await_count == 1  # 不重试
    sleep.assert_not_awaited()  # 不退避空等


@pytest.mark.asyncio
async def test_edit_raises_after_exhausting_retries(tmp_path, monkeypatch):
    """持续 403(5 次退避后仍失败)→ 抛 QwenImageError,不静默返回。"""
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "test-host")
    monkeypatch.setattr("hevi.image.qwen_image_service.asyncio.sleep", AsyncMock())

    img = tmp_path / "a.png"
    img.write_bytes(b"fake-a")

    forbidden = MagicMock()
    forbidden.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock())
    )
    client = _fake_client(forbidden, _fake_response({}))
    client.post = AsyncMock(return_value=forbidden)

    with patch("httpx.AsyncClient", return_value=client):
        with pytest.raises(QwenImageError, match="提交多次失败"):
            await qwen_image_edit(image_path=img, instruction="x", output_path=tmp_path / "out.png")
    assert client.post.await_count == 5


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
