"""CosyVoice TTS —— 轻量 HTTP 客户端(纯调度,零本地推理)。

v9.1 基建解耦: CosyVoice / LongCat 等重型推理已整体迁移到 GPU 算力引擎容器
(services/ai_engine), 本模块只负责:
  1. 把脚本文本 POST 到内网引擎端点 http://hevi-gen-engine:17493/api/ai/cosyvoice
  2. 等待引擎合成完成并下载 WAV 到 output_path

本模块不 import torch / transformers / oprim 推理原子 —— API 容器是纯控制节点。

参考音契约(cosy-ref-v1, 见 hevi.voicepro.schemas.COSY_CONTRACT_VERSION):
CosyVoice zero_shot / cross_lingual / instruct 都需要参考音。生产调用方(explainer
旁白、voice_platform API、各产品线 TTS)大多只传文本, 因此本模块在发请求前
**总是**为每行解析参考音: 行内 voice_ref → voice_id(内置名/studio 音色目录)
→ 身份包声线(config.identity_voice) → HEVI_COSY_DEFAULT_VOICE_REF →
仓库内置默认 ``builtin:zh_default``;都没有时显式走 sft(HEVI_COSY_SFT_SPEAKER)
或抛 :class:`CosyVoiceContractError`, 不再把无参考音的行发给引擎静默失败。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from hevi.layer4_legacy.voicepro.oskill_impl.cosy_payload import (
    bind_cosy_reference,
    resolve_cosy_reference,
)
from hevi.voicepro.schemas import COSY_CONTRACT_VERSION, CosyContractError

__all__ = [
    "AiEngineError",
    "CosyVoiceContractError",
    "cosyvoice_synthesize",
    "resolve_cosy_script",
]

logger = logging.getLogger(__name__)


class AiEngineError(RuntimeError):
    """AI 算力引擎不可用或返回了无效的生成结果。"""


class CosyVoiceContractError(AiEngineError, CosyContractError):
    """请求不满足 CosyVoice 参考音契约(发请求前即失败, 不打引擎)。

    同时是 AiEngineError(调用方现有降级逻辑照常生效, 但带清晰原因)与
    ValueError(API 层映射为 422)。
    """


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
        if getattr(line, "voice_id", None):
            row["voice_id"] = str(line.voice_id)
        if getattr(line, "spk_id", None):
            row["spk_id"] = str(line.spk_id)
        rows.append(row)
    return rows


def _gallery_lookup(voice_id: str) -> tuple[str, str] | None:
    """voice_platform 用户音色(create_voice_profile)→ (参考音, 转录)。"""
    try:
        from hevi.layer4_legacy.voicepro.omodul_impl.platform import list_gallery_profiles
    except ImportError:  # pragma: no cover - 平台模块可选
        return None
    for item in list_gallery_profiles():
        if voice_id in {item.get("profile_id"), item.get("name")} and item.get("reference_audio"):
            return str(item["reference_audio"]), str(item.get("reference_text") or "")
    return None


def _catalog_lookup(voice_id: str) -> tuple[str, str] | None:
    """用户音色库 / studio 音色目录 → (参考音路径, 转录)。未知返回 None, 未拉取抛契约错误。"""
    gallery = _gallery_lookup(voice_id)
    if gallery is not None:
        return gallery
    try:
        from hevi.studio.voices import find_voice
    except ImportError:  # pragma: no cover - studio 可选
        return None
    spec = find_voice(voice_id)
    if spec is None:
        return None
    if not spec.local:
        raise CosyContractError(
            f"音色 '{spec.display}' 的参考音未拉取到本地: 先执行 asset.pull pack=celebrities30s"
        )
    return spec.audio_path, spec.transcript


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def resolve_cosy_script(
    rows: list[dict[str, Any]], *, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """为每行解析参考音并按 cosy-ref-v1 契约校验, 返回可直接下发引擎的行。"""
    cfg = config or {}
    env_ref = os.environ.get("HEVI_COSY_DEFAULT_VOICE_REF", "").strip()
    env_default = (env_ref, os.environ.get("HEVI_COSY_DEFAULT_REF_TEXT", "")) if env_ref else None
    allow_builtin = bool(
        cfg["allow_builtin_ref"]
        if cfg.get("allow_builtin_ref") is not None
        else _env_flag("HEVI_COSY_BUILTIN_REF", True)
    )
    cfg_voice = cfg.get("voice_id") or cfg.get("voice")
    sft_default = cfg.get("sft_speaker") or os.environ.get("HEVI_COSY_SFT_SPEAKER")
    identity = cfg.get("identity_voice") if isinstance(cfg.get("identity_voice"), dict) else None
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            reference = resolve_cosy_reference(
                voice_ref=row.get("voice_ref"),
                ref_text=row.get("ref_text") or row.get("prompt_text"),
                voice_id=row.get("voice_id") or cfg_voice,
                identity_voice=identity,
                catalog_lookup=_catalog_lookup,
                env_default=env_default,
                allow_builtin=allow_builtin,
                sft_speaker=row.get("spk_id") or sft_default,
                requested_mode=row.get("inference_mode"),
                strict_voice_id=bool(cfg.get("strict_voice")),
            )
            bound = bind_cosy_reference(row=row, reference=reference)
        except CosyContractError as exc:
            raise CosyVoiceContractError(f"script[{index}]: {exc}") from exc
        logger.info(
            "cosyvoice contract: script[%d] ref_source=%s mode=%s",
            index,
            bound.get("ref_source"),
            bound.get("inference_mode"),
        )
        out.append(bound)
    return out


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
    rows = resolve_cosy_script(rows, config=cfg)
    payload = {
        "script": rows,
        "config": {
            "contract": COSY_CONTRACT_VERSION,
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
                raise AiEngineError(f"AI 引擎无 CosyVoice 模型可用: {_detail(response)}")
            if response.status_code >= 400:
                raise AiEngineError(
                    f"AI 引擎 CosyVoice 合成失败 (HTTP {response.status_code}): {_detail(response)}"
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
    except ValueError, json.JSONDecodeError:
        pass
    return response.text[:300] or f"HTTP {response.status_code}"
