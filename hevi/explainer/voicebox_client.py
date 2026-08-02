"""Small HTTP client for the Voicebox sidecar used by explainer E2.

Voicebox intentionally owns model loading, profiles and its serial GPU queue.
HEVI only submits text, waits for the terminal generation event, and downloads
the resulting audio into the run's Remotion audio directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


class VoiceboxError(RuntimeError):
    """Voicebox is unavailable or returned an invalid generation."""


def _base_url() -> str:
    return os.environ.get("VOICEBOX_BASE_URL", "http://voicebox:17493").rstrip("/")


def _profile_id() -> str | None:
    value = os.environ.get("VOICEBOX_PROFILE_ID", "").strip()
    return value or None


async def _response_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            return str(detail)
    except (ValueError, json.JSONDecodeError, httpx.ResponseNotRead):
        pass
    return response.text[:500] or f"HTTP {response.status_code}"


async def _ensure_profile(client: httpx.AsyncClient) -> str:
    configured = _profile_id()
    if configured:
        return configured

    response = await client.get("/profiles")
    if response.status_code >= 400:
        raise VoiceboxError(f"无法读取 Voicebox 音色档案: {await _response_error(response)}")
    profiles = response.json()
    if profiles:
        return str(profiles[0]["id"])

    # A fresh deployment needs a usable Chinese profile before the first run.
    # Users can replace it with a cloned profile by setting VOICEBOX_PROFILE_ID.
    response = await client.post(
        "/profiles",
        json={
            "name": "HEVI 解说",
            "description": "HEVI explainer default Chinese narration voice",
            "language": "zh",
            "voice_type": "preset",
            "preset_engine": "qwen_custom_voice",
            "preset_voice_id": os.environ.get("VOICEBOX_PRESET_VOICE", "Dylan"),
            "default_engine": "qwen_custom_voice",
        },
    )
    if response.status_code >= 400:
        raise VoiceboxError(f"无法创建 Voicebox 默认音色: {await _response_error(response)}")
    return str(response.json()["id"])


async def synthesize(
    text: str,
    output_path: Path,
    *,
    instruct: str | None = None,
) -> None:
    """Generate one segment and write Voicebox's WAV response to *output_path*."""

    timeout = httpx.Timeout(
        float(os.environ.get("VOICEBOX_TIMEOUT_S", "900")),
        connect=float(os.environ.get("VOICEBOX_CONNECT_TIMEOUT_S", "15")),
    )
    async with httpx.AsyncClient(base_url=_base_url(), timeout=timeout) as client:
        try:
            profile_id = await _ensure_profile(client)
            payload = {
                "profile_id": profile_id,
                "text": text,
                "language": "zh",
                "engine": os.environ.get("VOICEBOX_ENGINE", "qwen_custom_voice"),
                "model_size": os.environ.get("VOICEBOX_MODEL_SIZE", "1.7B"),
                "instruct": instruct
                or os.environ.get(
                    "VOICEBOX_INSTRUCT",
                    "自然、沉稳、有呼吸感的中文纪录片解说，语气有轻微起伏，不要播音腔，不要机械停顿。",
                ),
                "max_chunk_chars": int(os.environ.get("VOICEBOX_MAX_CHUNK_CHARS", "800")),
                "crossfade_ms": int(os.environ.get("VOICEBOX_CROSSFADE_MS", "50")),
                "normalize": True,
            }
            response = await client.post("/generate", json=payload)
            if response.status_code >= 400:
                raise VoiceboxError(f"Voicebox 生成请求失败: {await _response_error(response)}")
            generation = response.json()
            generation_id = generation.get("id")
            if not generation_id:
                raise VoiceboxError("Voicebox 返回缺少 generation id")

            terminal = await _wait_for_generation(client, str(generation_id))
            if terminal.get("status") != "completed":
                reason = terminal.get("error") or terminal.get("status", "unknown")
                raise VoiceboxError(
                    f"Voicebox 生成失败: {reason}"
                )

            audio = await client.get(f"/audio/{generation_id}")
            if audio.status_code >= 400:
                raise VoiceboxError(f"Voicebox 音频下载失败: {await _response_error(audio)}")
            if not audio.content:
                raise VoiceboxError("Voicebox 返回空音频")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio.content)
        except VoiceboxError:
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise VoiceboxError(f"Voicebox 服务不可用: {exc}") from exc


async def _wait_for_generation(client: httpx.AsyncClient, generation_id: str) -> dict:
    """Consume Voicebox's SSE status stream and return its terminal payload."""

    try:
        async with client.stream("GET", f"/generate/{generation_id}/status") as response:
            if response.status_code >= 400:
                await response.aread()
                raise VoiceboxError(f"Voicebox 状态查询失败: {await _response_error(response)}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if payload.get("status") in {"completed", "failed", "not_found"}:
                    return payload
    except VoiceboxError:
        raise
    except httpx.HTTPError as exc:
        raise VoiceboxError(f"Voicebox 状态流断开: {exc}") from exc
    raise VoiceboxError("Voicebox 状态流未返回终态")
