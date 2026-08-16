"""fish-speech TTS —— 轻量 HTTP 客户端(纯调度, 零本地推理)。

v9.1 基建解耦: fish-speech-1.5 零样本语音合成在 GPU 算力引擎容器
(services/ai_engine)内执行, 本模块只负责:
  1. 把文本(+可选参考音频) POST 到内网引擎端点
     http://hevi-gen-engine:17493/api/ai/fish_speech
  2. 等待引擎合成完成并下载 WAV 到 output_path

引擎无模型/库缺失 → AiEngineError(501), 调用方决定降级。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

__all__ = ["fish_speech_synthesize"]


class FishSpeechError(RuntimeError):
    """AI 引擎 fish-speech 不可用或返回无效结果。"""


def _base_url() -> str:
    # 生成引擎: GEN_ENGINE_BASE_URL 优先, AI_ENGINE_BASE_URL 兼容回退。
    url = (
        os.environ.get("GEN_ENGINE_BASE_URL")
        or os.environ.get("AI_ENGINE_BASE_URL")
        or "http://hevi-gen-engine:17493"
    )
    return url.rstrip("/")


async def fish_speech_synthesize(
    text: str,
    output_path: Path | str,
    *,
    reference_audio_path: Path | str | None = None,
) -> Path:
    """委托引擎合成一段语音并写入 *output_path*。

    参考音频缺省时引擎使用内置音色; 引擎缺失/无模型抛
    :class:`FishSpeechError`(501 语义), 由调用方决定降级。
    """
    if not text.strip():
        raise ValueError("text 不能为空")

    timeout = httpx.Timeout(
        float(os.environ.get("AI_ENGINE_TIMEOUT_S", "600")),
        connect=float(os.environ.get("AI_ENGINE_CONNECT_TIMEOUT_S", "15")),
    )
    files: dict[str, tuple[str, bytes, str]] = {
        "text": ("text.txt", text.encode("utf-8"), "text/plain"),
    }
    if reference_audio_path is not None:
        ref = Path(reference_audio_path)
        if ref.exists() and ref.stat().st_size > 0:
            files["reference_audio"] = (ref.name, ref.read_bytes(), "audio/wav")

    try:
        async with httpx.AsyncClient(base_url=_base_url(), timeout=timeout) as client:
            response = await client.post("/api/ai/fish_speech", files=files)
            if response.status_code == 501:
                raise FishSpeechError(f"AI 引擎无 fish-speech 可用: {_detail(response)}")
            if response.status_code >= 400:
                raise FishSpeechError(
                    f"AI 引擎 fish-speech 合成失败 (HTTP {response.status_code}): "
                    f"{_detail(response)}"
                )
            if not response.content:
                raise FishSpeechError("AI 引擎返回空音频")
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(response.content)
    except FishSpeechError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise FishSpeechError(f"AI 引擎服务不可用: {exc}") from exc

    if not out.exists() or out.stat().st_size == 0:
        raise FishSpeechError(f"AI 引擎未产出音频文件: {out}")
    return out


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except (ValueError, json.JSONDecodeError):
        pass
    return response.text[:300] or f"HTTP {response.status_code}"


