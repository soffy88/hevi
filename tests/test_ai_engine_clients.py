"""v9.1 基建解耦: hevi-api 纯客户端行为测试。

验证 CosyVoice / LongCat 已从"本地推理"改为"HTTP 调用 AI 引擎"——
API 容器不再加载任何模型, 引擎不可达/无模型时按契约降级。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hevi.audio.cosyvoice_service import AiEngineError, cosyvoice_synthesize
from hevi.digital_human.talking_face import (
    TalkingFaceUnavailable,
    generate_talking_face,
)


class _FakeAsyncClient:
    """最小 AsyncClient 替身: 只实现 post/get 与 async context manager。"""

    def __init__(
        self,
        post_response: httpx.Response | None = None,
        get_response: httpx.Response | None = None,
    ):
        self.post = AsyncMock(return_value=post_response or httpx.Response(200, content=b"WAV"))
        self.get = AsyncMock(return_value=get_response or httpx.Response(200, json={}))
        self._raise_on_post: Exception | None = None

    def raise_on_post(self, exc: Exception) -> None:
        self._raise_on_post = exc
        self.post = AsyncMock(side_effect=exc)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _patch_client(
    post_response: httpx.Response | None = None,
    get_response: httpx.Response | None = None,
):
    fake = _FakeAsyncClient(post_response=post_response, get_response=get_response)
    patcher = patch("hevi.audio.cosyvoice_service.httpx.AsyncClient", return_value=fake)
    return patcher, fake


@pytest.mark.asyncio
async def test_cosyvoice_posts_json_and_writes_wav(tmp_path: Path) -> None:
    """cosyvoice_synthesize 应把脚本序列化 POST 给引擎, 并把返回的 wav 落盘。"""
    patcher, fake = _patch_client(
        post_response=httpx.Response(200, content=b"RIFF...fake-wav-bytes")
    )
    out = tmp_path / "seg.wav"
    with patcher:
        result = await cosyvoice_synthesize(
            script=[SimpleNamespace(text="第一段", speaker_id="host")],
            output_path=out,
        )
    assert result == out
    assert out.read_bytes() == b"RIFF...fake-wav-bytes"
    # 请求体: script 行被压成 JSON(含 text), 走 /api/ai/cosyvoice。
    sent = fake.post.await_args
    assert sent is not None
    assert sent.args[0] == "/api/ai/cosyvoice"
    body = sent.kwargs["json"]
    assert body["script"][0]["text"] == "第一段"


@pytest.mark.asyncio
async def test_cosyvoice_501_raises_engine_error(tmp_path: Path) -> None:
    """引擎无模型(501) → AiEngineError, 由 voiceover 决定是否降级 edge_tts。"""
    patcher, _ = _patch_client(
        post_response=httpx.Response(501, json={"detail": "未部署 CosyVoice 模型"})
    )
    with patcher, pytest.raises(AiEngineError, match="未部署 CosyVoice"):
        await cosyvoice_synthesize(
            script=[SimpleNamespace(text="hi")],
            output_path=tmp_path / "out.wav",
        )


@pytest.mark.asyncio
async def test_cosyvoice_engine_down_raises(tmp_path: Path) -> None:
    """引擎容器不可达 → AiEngineError(HTTPError 被包装)。"""
    patcher, fake = _patch_client()
    fake.raise_on_post(httpx.ConnectError("engine unreachable"))
    with patcher, pytest.raises(AiEngineError, match="不可用"):
        await cosyvoice_synthesize(
            script=[SimpleNamespace(text="hi")],
            output_path=tmp_path / "out.wav",
        )


@pytest.mark.asyncio
async def test_cosyvoice_empty_script_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        await cosyvoice_synthesize(script=[], output_path=tmp_path / "out.wav")


# ─── Talking Face ───────────────────────────────────────────────────


def _fake_image(tmp_path: Path) -> Path:
    p = tmp_path / "presenter.jpg"
    p.write_bytes(b"fake-jpeg")
    return p


def _fake_audio(tmp_path: Path) -> Path:
    p = tmp_path / "master.wav"
    p.write_bytes(b"fake-wav")
    return p


def _placeholder_writer(out: Path):
    """生成一个会真实产出文件的占位函数 mock。"""

    async def _write(*_args: object, **_kwargs: object) -> Path:
        out.write_bytes(b"fake-mp4")
        return out

    return _write


@pytest.mark.asyncio
async def test_talking_face_falls_back_when_no_longcat_model(tmp_path: Path) -> None:
    """引擎可达但无 LongCat 模型 → 本地占位动画, 不抛错。"""
    image = _fake_image(tmp_path)
    audio = _fake_audio(tmp_path)
    out = tmp_path / "track.mp4"
    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": False}),
        ),
        patch(
            "hevi.digital_human.talking_face._generate_placeholder_avoiding_null",
            _placeholder_writer(out),
        ),
    ):
        result = await generate_talking_face(
            image_path=image, audio_path=audio, output_path=out
        )
    assert result == out


@pytest.mark.asyncio
async def test_talking_face_engine_501_degrades(tmp_path: Path) -> None:
    """引擎声明 longcat 可用但推理 501 → 捕获后走占位降级。"""
    image = _fake_image(tmp_path)
    audio = _fake_audio(tmp_path)
    out = tmp_path / "track.mp4"
    with (
        patch(
            "hevi.digital_human.talking_face._engine_capabilities",
            AsyncMock(return_value={"longcat": True}),
        ),
        patch(
            "hevi.digital_human.talking_face._run_engine_longcat",
            AsyncMock(side_effect=TalkingFaceUnavailable("引擎无 LongCat 模型")),
        ),
        patch(
            "hevi.digital_human.talking_face._generate_placeholder_avoiding_null",
            _placeholder_writer(out),
        ),
    ):
        result = await generate_talking_face(
            image_path=image, audio_path=audio, output_path=out
        )
    assert result == out


@pytest.mark.asyncio
async def test_talking_face_missing_inputs_rejected(tmp_path: Path) -> None:
    with pytest.raises(TalkingFaceUnavailable, match="Presenter image"):
        await generate_talking_face(
            image_path=tmp_path / "missing.jpg",
            audio_path=_fake_audio(tmp_path),
            output_path=tmp_path / "o.mp4",
        )
