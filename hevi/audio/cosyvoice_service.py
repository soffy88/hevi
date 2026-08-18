"""CosyVoice TTS —— 轻量 HTTP 客户端(纯调度,零本地推理)。

v9.1 基建解耦: CosyVoice / LongCat 等重型推理已整体迁移到 GPU 算力引擎容器
(services/ai_engine), 本模块只负责:
  1. 把脚本文本 POST 到内网引擎端点 http://hevi-gen-engine:17493/api/ai/cosyvoice
  2. 等待引擎合成完成并下载 WAV 到 output_path

本模块不 import torch / transformers / oprim 推理原子 —— API 容器是纯控制节点。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

__all__ = ["AiEngineError", "cosyvoice_synthesize"]


class AiEngineError(RuntimeError):
    """AI 算力引擎不可用或返回了无效的生成结果。"""


def _base_url() -> str:
    # 生成引擎: GEN_ENGINE_BASE_URL 优先, AI_ENGINE_BASE_URL 兼容回退。
    url = (
        os.environ.get("GEN_ENGINE_BASE_URL")
        or os.environ.get("AI_ENGINE_BASE_URL")
        or "http://hevi-gen-engine:17493"
    )
    return url.rstrip("/")


def _endpoint() -> str:
    return f"{_base_url()}/api/ai/cosyvoice"


def _serialize_script(script: list[Any]) -> list[dict[str, Any]]:
    """把 voiceover/audio_router 传入的 script 行(SimpleNamespace/对象)压成 JSON。"""
    rows: list[dict[str, Any]] = []
    for line in script:
        text = getattr(line, "text", None) or str(line)
        row: dict[str, Any] = {"text": text}
        if getattr(line, "speaker_id", None):
            row["speaker_id"] = line.speaker_id
        if getattr(line, "voice_ref", None):
            row["voice_ref"] = str(line.voice_ref)
        if getattr(line, "ref_text", None):
            row["ref_text"] = str(line.ref_text)
        if getattr(line, "speed", None):
            row["speed"] = float(line.speed)
        if getattr(line, "inference_mode", None):
            row["inference_mode"] = str(line.inference_mode)
        if getattr(line, "instruct_text", None):
            row["instruct_text"] = str(line.instruct_text)
        if getattr(line, "prompt_text", None):
            row["prompt_text"] = str(line.prompt_text)
        rows.append(row)
    return rows


async def cosyvoice_synthesize(
    *,
    config: dict[str, Any] | None = None,
    script: list[Any],
    output_path: Path,
    watermark: bool = True,
) -> Path:
    """委托 GPU 引擎合成一段解说音频并写入 *output_path*。

    与旧实现(本地 oprim/vibevoice 子进程)保持同一签名, 但不再在 API 容器里
    加载任何模型。引擎缺失/无模型时抛 :class:`AiEngineError`, 由调用方
    (voiceover / audio_router) 决定是否降级 edge_tts。
    """
    if not script:
        raise ValueError("Script cannot be empty")

    cfg = config or {}
    model_choice = str(cfg.get("model") or "").strip()
    env_mode = os.environ.get("HEVI_COSY_INFERENCE_MODE") or ""
    default_mode = str(cfg.get("inference_mode") or env_mode).strip()
    rows = _serialize_script(script)
    if default_mode:
        for row in rows:
            row.setdefault("inference_mode", default_mode)
    payload = {
        "script": rows,
        "config": {
            "model_dir": cfg.get("COSYVOICE_MODEL_DIR")
            or os.environ.get("COSYVOICE_MODEL_DIR")
            or None,
            "model": model_choice or None,
            "watermark": bool(
                cfg.get("COSYVOICE_USE_WATERMARK", watermark)
                if cfg.get("COSYVOICE_USE_WATERMARK") is not None
                else watermark
            ),
            "inference_mode": default_mode or None,
        },
    }

    timeout = httpx.Timeout(
        float(os.environ.get("AI_ENGINE_TIMEOUT_S", "900")),
        connect=float(os.environ.get("AI_ENGINE_CONNECT_TIMEOUT_S", "15")),
    )
    try:
        async with httpx.AsyncClient(base_url=_base_url(), timeout=timeout) as client:
            response = await client.post("/api/ai/cosyvoice", json=payload)
            if response.status_code == 501:
                raise AiEngineError(
                    f"AI 引擎无 CosyVoice 模型可用: {_detail(response)}"
                )
            if response.status_code >= 400:
                raise AiEngineError(
                    f"AI 引擎 CosyVoice 合成失败 (HTTP {response.status_code}): "
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
    except (ValueError, json.JSONDecodeError):
        pass
    return response.text[:300] or f"HTTP {response.status_code}"
