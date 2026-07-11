"""hevi.video.wavespeed_service — WaveSpeed AI(HappyHorse 1.1 / Wan 2.7)测试。
全部 mock httpx,不打真实 API(会真的花钱/消耗额度)。"""

from __future__ import annotations

import base64
import json as json_module
from typing import Any

import pytest

from hevi.video.wavespeed_service import (
    WaveSpeedError,
    happyhorse_1_1_generate,
    happyhorse_1_1_reference_to_video,
    wan_2_7_generate,
    wavespeed_generate,
    wavespeed_reference_generate,
)


class _FakeResponse:
    def __init__(
        self, *, json_data: dict[str, Any] | None = None, content: bytes = b"", status: int = 200
    ):
        self._json = json_data or {}
        self.content = content
        self.status_code = status
        self.text = json_module.dumps(self._json)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict[str, Any]:
        return self._json


class _FakeAsyncClient:
    """按调用顺序回放响应队列;记录每次调用的 (method, url) 供断言。"""

    def __init__(self, responses: list[_FakeResponse], calls: list[tuple[str, str]]):
        self._responses = list(responses)
        self._calls = calls

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, **kw: Any) -> _FakeResponse:
        self._calls.append(("POST", url))
        return self._responses.pop(0)

    async def get(self, url: str, **kw: Any) -> _FakeResponse:
        self._calls.append(("GET", url))
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses: list[_FakeResponse]) -> list[tuple[str, str]]:
    import hevi.video.wavespeed_service as ws_mod

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        ws_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(responses, calls)
    )
    return calls


@pytest.mark.asyncio
async def test_unknown_model_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    with pytest.raises(WaveSpeedError, match="unknown WaveSpeed model"):
        await wavespeed_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="not-a-real-model"
        )


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    with pytest.raises(WaveSpeedError, match="WAVESPEED_API_KEY"):
        await wavespeed_generate(prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7")


@pytest.mark.asyncio
async def test_successful_generation_downloads_video(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    out = tmp_path / "out.mp4"
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),  # POST submit
        _FakeResponse(json_data={"data": {"status": "processing"}}),  # GET poll 1
        _FakeResponse(
            json_data={"data": {"status": "completed", "outputs": ["http://cdn/video.mp4"]}}
        ),  # GET poll 2 — done
        _FakeResponse(content=b"x" * 2000),  # GET video download (must clear min-size check)
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await wan_2_7_generate(
        prompt="a cat on a fence", output_path=out, poll_interval_s=0.01
    )

    assert result == out
    assert out.read_bytes() == b"x" * 2000
    assert calls[0] == ("POST", "https://api.wavespeed.ai/api/v3/alibaba/wan-2.7/text-to-video")
    assert "predictions/REQ1/result" in calls[1][1]
    assert calls[-1] == ("GET", "http://cdn/video.mp4")


@pytest.mark.asyncio
async def test_happyhorse_hits_its_own_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"id": "REQ2"}),  # top-level id, no "data" wrapper
        _FakeResponse(json_data={"status": "completed", "outputs": ["http://cdn/v2.mp4"]}),
        _FakeResponse(content=b"y" * 2000),
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await happyhorse_1_1_generate(
        prompt="a dancer spinning", output_path=tmp_path / "out.mp4", poll_interval_s=0.01
    )
    assert result.exists()
    assert calls[0] == (
        "POST",
        "https://api.wavespeed.ai/api/v3/alibaba/happyhorse-1.1/text-to-video",
    )


@pytest.mark.asyncio
async def test_config_dict_overrides_env_key(monkeypatch, tmp_path):
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),
        _FakeResponse(json_data={"data": {"status": "completed", "outputs": ["http://cdn/v.mp4"]}}),
        _FakeResponse(content=b"z" * 2000),
    ]
    _patch_client(monkeypatch, responses)

    result = await wavespeed_generate(
        prompt="x",
        output_path=tmp_path / "out.mp4",
        model="wan_2_7",
        config={"WAVESPEED_API_KEY": "from-config"},
        poll_interval_s=0.01,
    )
    assert result.exists()


@pytest.mark.asyncio
async def test_failed_status_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),
        _FakeResponse(json_data={"data": {"status": "failed", "error": "CONTENT_VIOLATION"}}),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="CONTENT_VIOLATION"):
        await wavespeed_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


@pytest.mark.asyncio
async def test_completed_with_no_outputs_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),
        _FakeResponse(json_data={"data": {"status": "completed", "outputs": []}}),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="无产物"):
        await wavespeed_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),
        *[_FakeResponse(json_data={"data": {"status": "processing"}}) for _ in range(5)],
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="未完成"):
        await wavespeed_generate(
            prompt="x",
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",
            poll_interval_s=0.01,
            timeout_s=0.03,
        )


@pytest.mark.asyncio
async def test_missing_request_id_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [_FakeResponse(json_data={})]
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="缺少任务 id"):
        await wavespeed_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="happyhorse_1_1"
        )


@pytest.mark.asyncio
async def test_empty_output_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),
        _FakeResponse(json_data={"data": {"status": "completed", "outputs": ["http://cdn/v.mp4"]}}),
        _FakeResponse(content=b"tiny"),  # under the 1024-byte floor
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="空/过小"):
        await wavespeed_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


# ── reference-to-video(智伯这类参考图锁脸场景,只有 happyhorse_1_1 提供)──────


@pytest.mark.asyncio
async def test_reference_generate_passes_through_http_url_without_upload(monkeypatch, tmp_path):
    """已经是 http(s) URL 的参考图直接透传,不应该多打一次上传请求。"""
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    out = tmp_path / "out.mp4"
    responses = [
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),  # POST submit(无上传步骤)
        _FakeResponse(json_data={"data": {"status": "completed", "outputs": ["http://cdn/v.mp4"]}}),
        _FakeResponse(content=b"x" * 2000),
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await happyhorse_1_1_reference_to_video(
        prompt="智伯举杯",
        reference_images=["http://x/ref1.png"],
        output_path=out,
        poll_interval_s=0.01,
    )

    assert result == out
    assert calls[0] == (
        "POST",
        "https://api.wavespeed.ai/api/v3/alibaba/happyhorse-1.1/reference-to-video",
    )
    assert not any("upload" in c[1] for c in calls)  # 没有额外的上传调用


@pytest.mark.asyncio
async def test_reference_generate_uploads_data_uri_first(monkeypatch, tmp_path):
    """data: URI 参考图要先经 WaveSpeed 上传端点换成 download_url,再拿这个 URL 提交生成。"""
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    out = tmp_path / "out.mp4"
    data_uri = "data:image/png;base64," + base64.b64encode(b"fake-png-bytes").decode()
    responses = [
        _FakeResponse(json_data={"data": {"download_url": "http://cdn/uploaded.png"}}),  # 上传
        _FakeResponse(json_data={"data": {"id": "REQ1"}}),  # 提交生成
        _FakeResponse(json_data={"data": {"status": "completed", "outputs": ["http://cdn/v.mp4"]}}),
        _FakeResponse(content=b"y" * 2000),
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await wavespeed_reference_generate(
        prompt="智伯举杯", reference_images=[data_uri], output_path=out, poll_interval_s=0.01
    )

    assert result == out
    assert calls[0] == ("POST", "https://api.wavespeed.ai/api/v3/media/upload/binary")
    assert calls[1] == (
        "POST",
        "https://api.wavespeed.ai/api/v3/alibaba/happyhorse-1.1/reference-to-video",
    )


@pytest.mark.asyncio
async def test_reference_generate_upload_missing_download_url_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    data_uri = "data:image/png;base64," + base64.b64encode(b"bytes").decode()
    responses = [_FakeResponse(json_data={"data": {}})]  # 上传响应缺 download_url
    _patch_client(monkeypatch, responses)

    with pytest.raises(WaveSpeedError, match="download_url"):
        await wavespeed_reference_generate(
            prompt="x", reference_images=[data_uri], output_path=tmp_path / "out.mp4"
        )


@pytest.mark.asyncio
async def test_reference_generate_rejects_unsupported_image_format(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    with pytest.raises(WaveSpeedError, match="unsupported reference image format"):
        await wavespeed_reference_generate(
            prompt="x",
            reference_images=["not-a-url-or-data-uri"],
            output_path=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_reference_generate_rejects_too_many_images(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    with pytest.raises(WaveSpeedError, match="1-9"):
        await wavespeed_reference_generate(
            prompt="x",
            reference_images=[f"http://x/{i}.png" for i in range(10)],
            output_path=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_reference_generate_rejects_zero_images(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    with pytest.raises(WaveSpeedError, match="1-9"):
        await wavespeed_reference_generate(
            prompt="x", reference_images=[], output_path=tmp_path / "out.mp4"
        )


@pytest.mark.asyncio
async def test_reference_generate_unknown_model_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WAVESPEED_API_KEY", "test-key")
    with pytest.raises(WaveSpeedError, match="reference-to-video 目前只支持"):
        await wavespeed_reference_generate(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",  # Wan 2.7 没有纯图片参考端点(见模块 docstring)
        )


@pytest.mark.asyncio
async def test_reference_generate_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("WAVESPEED_API_KEY", raising=False)
    with pytest.raises(WaveSpeedError, match="WAVESPEED_API_KEY"):
        await wavespeed_reference_generate(
            prompt="x", reference_images=["http://x/1.png"], output_path=tmp_path / "out.mp4"
        )
