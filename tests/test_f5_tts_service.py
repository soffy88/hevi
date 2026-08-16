"""F5-TTS 客户端(f5_tts_service)行为测试。

与 test_ai_engine_clients 同构: 验证 hevi-api 只做 HTTP 调度——
multipart POST(文本 + 参考音频 + 参考转录)给引擎端点, 引擎不可达/无模型
(501)时按契约抛 AiEngineError(调用方降级), 不加载任何本地模型。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hevi.audio.f5_tts_service import AiEngineError, f5_tts_synthesize


class _FakeAsyncClient:
    def __init__(self, post_response: httpx.Response | None = None):
        self.post = AsyncMock(return_value=post_response or httpx.Response(200, content=b"WAV"))
        self._raise_on_post: Exception | None = None

    def raise_on_post(self, exc: Exception) -> None:
        self.post = AsyncMock(side_effect=exc)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


def _patch_client(post_response: httpx.Response | None = None):
    fake = _FakeAsyncClient(post_response=post_response)
    patcher = patch("hevi.audio.f5_tts_service.httpx.AsyncClient", return_value=fake)
    return patcher, fake


@pytest.mark.asyncio
async def test_f5_posts_multipart_and_writes_wav(tmp_path: Path) -> None:
    """f5_tts_synthesize 应 multipart POST(text+参考音频+参考转录), 落盘 wav。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-ref")
    out = tmp_path / "out.wav"
    patcher, fake = _patch_client(
        post_response=httpx.Response(200, content=b"RIFF...fake-wav-bytes")
    )
    with patcher:
        result = await f5_tts_synthesize(
            text="大雾锁江",
            output_path=out,
            reference_audio=ref,
            reference_text="这是参考音频的转录",
            speed=1.2,
            seed=42,
        )
    assert result == out
    assert out.read_bytes() == b"RIFF...fake-wav-bytes"
    sent = fake.post.call_args
    assert sent.args[0] == "/api/ai/f5_tts"
    data, files = sent.kwargs["data"], sent.kwargs["files"]
    assert data["text"] == "大雾锁江"
    assert data["reference_text"] == "这是参考音频的转录"
    assert data["speed"] == "1.2"
    assert data["seed"] == "42"
    assert files["reference_audio"][0] == "ref.wav"


@pytest.mark.asyncio
async def test_f5_missing_reference_text_rejected(tmp_path: Path) -> None:
    """reference_text 缺失时客户端直接拒绝(不空转引擎)。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-ref")
    with pytest.raises(ValueError, match="reference_text 必填"):
        await f5_tts_synthesize(
            text="x", output_path=tmp_path / "o.wav",
            reference_audio=ref, reference_text="  ",
        )


@pytest.mark.asyncio
async def test_f5_missing_reference_audio_rejected(tmp_path: Path) -> None:
    """参考音频文件不存在时抛 AiEngineError(调用方可见原因)。"""
    with pytest.raises(AiEngineError, match="参考音频不存在"):
        await f5_tts_synthesize(
            text="x", output_path=tmp_path / "o.wav",
            reference_audio=tmp_path / "nope.wav", reference_text="t",
        )


@pytest.mark.asyncio
async def test_f5_501_raises_engine_error(tmp_path: Path) -> None:
    """引擎无 F5-TTS 模型(501) → AiEngineError 带可读 detail。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-ref")
    patcher, _ = _patch_client(
        post_response=httpx.Response(501, json={"detail": "F5-TTS 模型未部署"})
    )
    with patcher, pytest.raises(AiEngineError, match="未部署"):
        await f5_tts_synthesize(
            text="x", output_path=tmp_path / "o.wav",
            reference_audio=ref, reference_text="t",
        )


@pytest.mark.asyncio
async def test_f5_engine_down_raises(tmp_path: Path) -> None:
    """引擎不可达(连接错误) → AiEngineError 可降级。"""
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF-fake-ref")
    patcher, fake = _patch_client()
    fake.raise_on_post(httpx.ConnectError("engine down"))
    with patcher, pytest.raises(AiEngineError, match="服务不可用"):
        await f5_tts_synthesize(
            text="x", output_path=tmp_path / "o.wav",
            reference_audio=ref, reference_text="t",
        )
