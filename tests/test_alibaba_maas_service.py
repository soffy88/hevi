"""hevi.video.alibaba_maas_service — 阿里云 Model Studio 业务空间专属域名测试。
全部 mock httpx,不打真实 API(会真的花钱/消耗额度)。"""

from __future__ import annotations

import json as json_module
from typing import Any

import pytest

from hevi.video.alibaba_maas_service import (
    AlibabaMaasError,
    alibaba_maas_generate,
    alibaba_maas_reference_generate,
    happyhorse_1_1_maas_generate,
    happyhorse_1_1_maas_reference_to_video,
    wan_2_7_maas_generate,
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
    import hevi.video.alibaba_maas_service as maas_mod

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        maas_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(responses, calls)
    )
    return calls


def _set_env(monkeypatch):
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "ws-test123.ap-southeast-1.maas.aliyuncs.com")


@pytest.mark.asyncio
async def test_unknown_model_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    with pytest.raises(AlibabaMaasError, match="unknown model"):
        await alibaba_maas_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="not-a-real-model"
        )


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("ALIBABA_MAAS_API_KEY", raising=False)
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "ws-test123.ap-southeast-1.maas.aliyuncs.com")
    with pytest.raises(AlibabaMaasError, match="ALIBABA_MAAS_API_KEY"):
        await alibaba_maas_generate(prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7")


@pytest.mark.asyncio
async def test_missing_host_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("ALIBABA_MAAS_API_KEY", "test-key")
    monkeypatch.delenv("ALIBABA_MAAS_HOST", raising=False)
    with pytest.raises(AlibabaMaasError, match="ALIBABA_MAAS_HOST"):
        await alibaba_maas_generate(prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7")


@pytest.mark.asyncio
async def test_successful_generation_downloads_video(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    out = tmp_path / "out.mp4"
    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "RUNNING"}}),
        _FakeResponse(
            json_data={
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": "http://cdn/video.mp4",
                }
            }
        ),
        _FakeResponse(content=b"x" * 2000),
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await wan_2_7_maas_generate(
        prompt="a cat on a fence", output_path=out, poll_interval_s=0.01
    )

    assert result == out
    assert out.read_bytes() == b"x" * 2000
    assert calls[0] == (
        "POST",
        "https://ws-test123.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
    )
    assert calls[1] == (
        "GET",
        "https://ws-test123.ap-southeast-1.maas.aliyuncs.com/api/v1/tasks/T1",
    )
    assert calls[-1] == ("GET", "http://cdn/video.mp4")


@pytest.mark.asyncio
async def test_happyhorse_uses_correct_model_id(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    captured_payloads = []

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url, json=None, **kw):
            captured_payloads.append(json)
            return await super().post(url, **kw)

    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),  # submit
        _FakeResponse(
            json_data={
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": "http://cdn/v.mp4",
                }
            }
        ),
        _FakeResponse(content=b"y" * 2000),
    ]
    calls: list[tuple[str, str]] = []
    import hevi.video.alibaba_maas_service as maas_mod

    monkeypatch.setattr(
        maas_mod.httpx, "AsyncClient", lambda **kw: _CapturingClient(responses, calls)
    )

    await happyhorse_1_1_maas_generate(
        prompt="a dancer spinning", output_path=tmp_path / "out.mp4", poll_interval_s=0.01
    )
    assert captured_payloads[0]["model"] == "happyhorse-1.1-t2v"


@pytest.mark.asyncio
async def test_config_dict_overrides_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ALIBABA_MAAS_API_KEY", raising=False)
    monkeypatch.delenv("ALIBABA_MAAS_HOST", raising=False)
    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),  # submit
        _FakeResponse(
            json_data={
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": "http://cdn/v.mp4",
                }
            }
        ),
        _FakeResponse(content=b"z" * 2000),
    ]
    _patch_client(monkeypatch, responses)

    result = await alibaba_maas_generate(
        prompt="x",
        output_path=tmp_path / "out.mp4",
        model="wan_2_7",
        config={
            "ALIBABA_MAAS_API_KEY": "from-config",
            "ALIBABA_MAAS_HOST": "ws-cfg.ap-southeast-1.maas.aliyuncs.com",
        },
        poll_interval_s=0.01,
    )
    assert result.exists()


@pytest.mark.asyncio
async def test_failed_status_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),
        _FakeResponse(
            json_data={
                "output": {"task_id": "T1", "task_status": "FAILED", "message": "content violation"}
            }
        ),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(AlibabaMaasError, match="失败"):
        await alibaba_maas_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


@pytest.mark.asyncio
async def test_succeeded_with_no_video_url_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),  # submit
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "SUCCEEDED"}}),  # poll
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(AlibabaMaasError, match="无 video_url"):
        await alibaba_maas_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    responses = [
        *[
            _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "RUNNING"}})
            for _ in range(5)
        ],
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(AlibabaMaasError, match="未完成"):
        await alibaba_maas_generate(
            prompt="x",
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",
            poll_interval_s=0.01,
            timeout_s=0.03,
        )


@pytest.mark.asyncio
async def test_missing_task_id_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    responses = [_FakeResponse(json_data={})]
    _patch_client(monkeypatch, responses)

    with pytest.raises(AlibabaMaasError, match="task_id"):
        await alibaba_maas_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="happyhorse_1_1"
        )


@pytest.mark.asyncio
async def test_empty_output_file_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),  # submit
        _FakeResponse(
            json_data={
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": "http://cdn/v.mp4",
                }
            }
        ),
        _FakeResponse(content=b"tiny"),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(AlibabaMaasError, match="空/过小"):
        await alibaba_maas_generate(
            prompt="x", output_path=tmp_path / "out.mp4", model="wan_2_7", poll_interval_s=0.01
        )


# ── reference-to-video(智伯这类参考图锁脸场景,只有 happyhorse_1_1 提供)──────


@pytest.mark.asyncio
async def test_reference_generate_builds_media_array(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    captured_payloads = []

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url, json=None, **kw):
            captured_payloads.append(json)
            return await super().post(url, **kw)

    responses = [
        _FakeResponse(json_data={"output": {"task_id": "T1", "task_status": "PENDING"}}),
        _FakeResponse(
            json_data={
                "output": {
                    "task_id": "T1",
                    "task_status": "SUCCEEDED",
                    "video_url": "http://cdn/v.mp4",
                }
            }
        ),
        _FakeResponse(content=b"x" * 2000),
    ]
    calls: list[tuple[str, str]] = []
    import hevi.video.alibaba_maas_service as maas_mod

    monkeypatch.setattr(
        maas_mod.httpx, "AsyncClient", lambda **kw: _CapturingClient(responses, calls)
    )

    result = await happyhorse_1_1_maas_reference_to_video(
        prompt="智伯举杯",
        reference_images=["http://x/ref1.png", "data:image/png;base64,Zm9v"],
        output_path=tmp_path / "out.mp4",
        poll_interval_s=0.01,
    )
    assert result.exists()
    payload = captured_payloads[0]
    assert payload["model"] == "happyhorse-1.1-r2v"
    assert payload["input"]["media"] == [
        {"type": "reference_image", "url": "http://x/ref1.png"},
        {"type": "reference_image", "url": "data:image/png;base64,Zm9v"},
    ]
    assert payload["parameters"]["watermark"] is False  # 默认关掉阿里的水印


@pytest.mark.asyncio
async def test_reference_generate_rejects_too_many_images(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    with pytest.raises(AlibabaMaasError, match="1-9"):
        await alibaba_maas_reference_generate(
            prompt="x",
            reference_images=[f"http://x/{i}.png" for i in range(10)],
            output_path=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_reference_generate_rejects_zero_images(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    with pytest.raises(AlibabaMaasError, match="1-9"):
        await alibaba_maas_reference_generate(
            prompt="x", reference_images=[], output_path=tmp_path / "out.mp4"
        )


@pytest.mark.asyncio
async def test_reference_generate_unknown_model_raises(monkeypatch, tmp_path):
    _set_env(monkeypatch)
    with pytest.raises(AlibabaMaasError, match="reference-to-video 目前只支持"):
        await alibaba_maas_reference_generate(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
            model="wan_2_7",  # Wan 2.7 在阿里目录里也没有纯图片参考端点
        )


@pytest.mark.asyncio
async def test_reference_generate_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("ALIBABA_MAAS_API_KEY", raising=False)
    monkeypatch.setenv("ALIBABA_MAAS_HOST", "ws-test123.ap-southeast-1.maas.aliyuncs.com")
    with pytest.raises(AlibabaMaasError, match="ALIBABA_MAAS_API_KEY"):
        await alibaba_maas_reference_generate(
            prompt="x", reference_images=["http://x/1.png"], output_path=tmp_path / "out.mp4"
        )
