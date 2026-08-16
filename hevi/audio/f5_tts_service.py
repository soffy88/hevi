"""F5-TTS 零样本音色克隆 —— 轻量 HTTP 客户端(纯调度, 零本地推理)。

与 cosyvoice_service 同构: 把文本 + 参考音频(克隆音色)+ 参考转录 POST 到
内网引擎端点 http://hevi-gen-engine:17493/api/ai/f5_tts, 下载 WAV 到 output_path。
API 容器不 import torch / f5_tts —— 推理在 GPU 引擎容器内完成。

参考音频来源约定:
  - 音色档案式用法: 调用方持有参考音频(如 Subject voice_ref)与对应转录文本;
  - 解说固定音色: audio_router 的 formal provider "f5" 读 F5_TTS_REFERENCE_AUDIO /
    F5_TTS_REFERENCE_TEXT(见 .env.example)。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

__all__ = ["AiEngineError", "f5_tts_synthesize"]


class AiEngineError(RuntimeError):
    """AI 算力引擎不可用或返回了无效的生成结果。"""


def _base_url() -> str:
    url = (
        os.environ.get("GEN_ENGINE_BASE_URL")
        or os.environ.get("AI_ENGINE_BASE_URL")
        or "http://hevi-gen-engine:17493"
    )
    return url.rstrip("/")


async def f5_tts_synthesize(
    *,
    text: str,
    output_path: Path,
    reference_audio: Path | str,
    reference_text: str,
    speed: float = 1.0,
    seed: int | None = None,
    timeout_s: float | None = None,
) -> Path:
    """委托 GPU 引擎用 F5-TTS 零样本克隆合成一段音频并写入 *output_path*。

    Args:
        text: 要合成的文本。
        reference_audio: 参考音频(克隆音色, ≤12s 自动截断)。
        reference_text: 参考音频的转录文本(必填; 引擎离线不自动转写)。
        speed: 语速 0.5~2.0。
        seed: 固定可复现(可选)。

    Raises:
        AiEngineError: 引擎缺失/无模型(501)/合成失败。
    """
    if not text.strip():
        raise ValueError("text 不能为空")
    if not reference_text.strip():
        raise ValueError("reference_text 必填(参考音频的转录文本)")

    ref = Path(reference_audio)
    if not ref.exists():
        raise AiEngineError(f"参考音频不存在: {ref}")

    timeout = httpx.Timeout(
        timeout_s or float(os.environ.get("AI_ENGINE_TIMEOUT_S", "600")),
        connect=float(os.environ.get("AI_ENGINE_CONNECT_TIMEOUT_S", "15")),
    )
    files: dict[str, Any] = {
        "reference_audio": (ref.name, ref.read_bytes(), "audio/wav"),
    }
    data: dict[str, Any] = {
        "text": text,
        "reference_text": reference_text,
        "speed": str(speed),
    }
    if seed is not None:
        data["seed"] = str(int(seed))

    try:
        async with httpx.AsyncClient(base_url=_base_url(), timeout=timeout) as client:
            response = await client.post("/api/ai/f5_tts", data=data, files=files)
            if response.status_code == 501:
                raise AiEngineError(
                    f"AI 引擎无 F5-TTS 模型可用: {_detail(response)}"
                )
            if response.status_code >= 400:
                raise AiEngineError(
                    f"AI 引擎 F5-TTS 合成失败 (HTTP {response.status_code}): "
                    f"{_detail(response)}"
                )
            if not response.content:
                raise AiEngineError("AI 引擎返回空音频")
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
    except AiEngineError:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise AiEngineError(f"AI 引擎服务不可用: {exc}") from exc

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AiEngineError(f"AI 引擎未产出音频文件: {output_path}")
    return output_path


def _detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])
    except (ValueError, TypeError):
        pass
    return response.text[:300] or f"HTTP {response.status_code}"
