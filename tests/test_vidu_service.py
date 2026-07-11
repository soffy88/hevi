"""hevi.video.vidu_service — Vidu Reference-to-Video 云 API 测试。全部 mock httpx,
不打真实 API(会真的花钱/消耗额度)。"""

from __future__ import annotations

import json as json_module
from pathlib import Path
from typing import Any

import pytest

from hevi.video.vidu_service import ViduError, vidu_reference_to_video


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
    """按调用顺序回放响应队列;记录每次调用的 (method, url, kwargs) 供断言。"""

    def __init__(self, responses: list[_FakeResponse], calls: list[tuple[str, str]]):
        self._responses = list(responses)
        self._calls = calls

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(
        self, url: str, json: dict | None = None, headers: dict | None = None
    ) -> _FakeResponse:
        self._calls.append(("POST", url))
        return self._responses.pop(0)

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self._calls.append(("GET", url))
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses: list[_FakeResponse]) -> list[tuple[str, str]]:
    import hevi.video.vidu_service as vidu_mod

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        vidu_mod.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(responses, calls)
    )
    return calls


@pytest.mark.asyncio
async def test_missing_api_key_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDU_API_KEY", raising=False)
    with pytest.raises(ViduError, match="VIDU_API_KEY"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_rejects_too_many_reference_images(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    with pytest.raises(ViduError, match="1-7"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=[f"http://x/{i}.png" for i in range(8)],
            output_path=tmp_path / "out.mp4",
        )


@pytest.mark.asyncio
async def test_successful_generation_downloads_video(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    out = tmp_path / "out.mp4"
    responses = [
        _FakeResponse(json_data={"task_id": "T1"}),  # POST submit
        _FakeResponse(json_data={"state": "processing"}),  # GET poll 1
        _FakeResponse(
            json_data={  # GET poll 2 — done
                "state": "success",
                "creations": [
                    {"id": "C1", "url": "http://cdn/video.mp4", "cover_url": "http://cdn/cover.jpg"}
                ],
            }
        ),
        _FakeResponse(content=b"fake-mp4-bytes"),  # GET video download
    ]
    calls = _patch_client(monkeypatch, responses)

    result = await vidu_reference_to_video(
        prompt="智伯举杯",
        reference_images=["http://x/ref.png"],
        output_path=out,
        poll_interval_s=0.01,
    )

    assert result == out
    assert out.read_bytes() == b"fake-mp4-bytes"
    assert calls[0] == ("POST", "https://api.vidu.com/ent/v2/reference2video")
    assert calls[1][0] == "GET" and "T1/creations" in calls[1][1]
    assert calls[-1] == ("GET", "http://cdn/video.mp4")


@pytest.mark.asyncio
async def test_config_dict_overrides_env_key(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDU_API_KEY", raising=False)
    responses = [
        _FakeResponse(json_data={"task_id": "T1"}),
        _FakeResponse(
            json_data={
                "state": "success",
                "creations": [{"id": "C1", "url": "http://cdn/v.mp4"}],
            }
        ),
        _FakeResponse(content=b"bytes"),
    ]
    _patch_client(monkeypatch, responses)

    result = await vidu_reference_to_video(
        prompt="x",
        reference_images=["http://x/1.png"],
        output_path=tmp_path / "out.mp4",
        config={"VIDU_API_KEY": "from-config"},
        poll_interval_s=0.01,
    )
    assert result.exists()


@pytest.mark.asyncio
async def test_failed_state_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"task_id": "T1"}),
        _FakeResponse(json_data={"state": "failed", "err_code": "CONTENT_VIOLATION"}),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(ViduError, match="CONTENT_VIOLATION"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0.01,
        )


@pytest.mark.asyncio
async def test_success_with_no_creations_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"task_id": "T1"}),
        _FakeResponse(json_data={"state": "success", "creations": []}),
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(ViduError, match="无产物"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0.01,
        )


@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    responses = [
        _FakeResponse(json_data={"task_id": "T1"}),
        *[_FakeResponse(json_data={"state": "processing"}) for _ in range(5)],
    ]
    _patch_client(monkeypatch, responses)

    with pytest.raises(ViduError, match="未完成"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
            poll_interval_s=0.01,
            timeout_s=0.03,
        )


@pytest.mark.asyncio
async def test_missing_task_id_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDU_API_KEY", "test-key")
    responses = [_FakeResponse(json_data={})]
    _patch_client(monkeypatch, responses)

    with pytest.raises(ViduError, match="task_id"):
        await vidu_reference_to_video(
            prompt="x",
            reference_images=["http://x/1.png"],
            output_path=tmp_path / "out.mp4",
        )
