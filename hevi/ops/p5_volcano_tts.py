"""HEVI P5 — Volcano Engine TTS Adapter.

Real provider integration through existing P3 provider registry.
No second provider registry. Uses existing capability catalog.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp

from hevi.ops.p5_types import (
    VoicePerformance,
    VoiceProfile,
    validate_voice_pacing,
)


_VOLCANO_API_BASE = "https://openspeech.bytedance.com/api/v1/tts"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class VolcanoTTSConfig:
    """Volcano TTS provider configuration."""
    app_id: str = ""
    access_token: str = ""
    cluster: str = "volcano_tts"
    voice_type: str = "BV001_streaming"
    base_url: str = _VOLCANO_API_BASE
    timeout_s: float = 60.0
    max_retries: int = 3
    retry_backoff_s: float = 2.0


@dataclass
class VolcanoTTSRequest:
    """Single TTS request payload."""
    text: str
    voice_type: str
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    emotion: str = "neutral"
    format: str = "wav"
    sample_rate: int = 24000
    enable_subtitle: bool = False


@dataclass
class VolcanoTTSResponse:
    """TTS response with audio and metadata."""
    success: bool
    audio_data: bytes | None = None
    audio_hash: str = ""
    duration_s: float = 0.0
    request_id: str = ""
    latency_s: float = 0.0
    error: str = ""
    subtitle_data: str = ""


class VolcanoTTSAdapter:
    """Volcano Engine TTS adapter with streaming support."""

    def __init__(self, config: VolcanoTTSConfig | None = None) -> None:
        self.config = config or VolcanoTTSConfig()
        self._session: aiohttp.ClientSession | None = None
        self._load_credentials()

    def _load_credentials(self) -> None:
        """Load credentials from environment."""
        self.config.app_id = os.getenv("VOLCANO_TTS_APP_ID", self.config.app_id)
        self.config.access_token = os.getenv("VOLCANO_TTS_ACCESS_TOKEN", self.config.access_token)
        self.config.base_url = os.getenv("VOLCANO_TTS_API_BASE", self.config.base_url)
        self.config.voice_type = os.getenv("VOLCANO_TTS_VOICE_TYPE", self.config.voice_type)

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_s)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
        }

    async def synthesize(
        self,
        text: str,
        voice_type: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        emotion: str = "neutral",
        output_path: Path | None = None,
    ) -> VolcanoTTSResponse:
        """Synthesize speech via Volcano TTS API."""
        session = await self._ensure_session()
        voice = voice_type or self.config.voice_type

        payload = {
            "app": {
                "appid": self.config.app_id,
                "token": self.config.access_token,
                "cluster": self.config.cluster,
            },
            "user": {
                "uid": "hevi_p5_user",
            },
            "audio": {
                "voice_type": voice,
                "encoding": "wav",
                "speed_ratio": speed,
                "pitch_ratio": pitch,
                "volume_ratio": 1.0,
            },
            "request": {
                "reqid": uuid.uuid4().hex[:16],
                "text": text,
                "text_type": "plain",
                "operation": "query",
            },
        }

        url = f"{self.config.base_url}/submit"
        request_id = uuid.uuid4().hex[:16]
        start = time.monotonic()

        for attempt in range(self.config.max_retries):
            try:
                async with session.post(url, json=payload, headers=self._build_headers()) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return VolcanoTTSResponse(
                            success=False,
                            error=f"HTTP {resp.status}: {error_text}",
                            request_id=request_id,
                            latency_s=time.monotonic() - start,
                        )

                    result = await resp.json()
                    if result.get("code") != 3000:
                        return VolcanoTTSResponse(
                            success=False,
                            error=f"API error: {result.get('message', 'unknown')}",
                            request_id=request_id,
                            latency_s=time.monotonic() - start,
                        )

                    audio_base64 = result.get("data", "")
                    if not audio_base64:
                        return VolcanoTTSResponse(
                            success=False,
                            error="Empty audio data in response",
                            request_id=request_id,
                            latency_s=time.monotonic() - start,
                        )

                    audio_data = base64.b64decode(audio_base64)
                    audio_hash = _sha256_bytes(audio_data)

                    if output_path:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(audio_data)

                    duration_s = len(audio_data) / (2 * 24000)

                    return VolcanoTTSResponse(
                        success=True,
                        audio_data=audio_data,
                        audio_hash=audio_hash,
                        duration_s=duration_s,
                        request_id=request_id,
                        latency_s=time.monotonic() - start,
                    )

            except asyncio.TimeoutError:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_backoff_s)
                    continue
                return VolcanoTTSResponse(
                    success=False,
                    error="Timeout after retries",
                    request_id=request_id,
                    latency_s=time.monotonic() - start,
                )
            except Exception as e:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_backoff_s)
                    continue
                return VolcanoTTSResponse(
                    success=False,
                    error=str(e),
                    request_id=request_id,
                    latency_s=time.monotonic() - start,
                )

        return VolcanoTTSResponse(
            success=False,
            error="Max retries exceeded",
            request_id=request_id,
            latency_s=time.monotonic() - start,
        )

    async def synthesize_streaming(
        self,
        text: str,
        voice_type: str | None = None,
        speed: float = 1.0,
        pitch: float = 1.0,
        emotion: str = "neutral",
        output_path: Path | None = None,
        chunk_callback: callable = None,
    ) -> VolcanoTTSResponse:
        chunks = self._split_text(text, max_len=500)
        all_audio = bytearray()
        total_latency = 0.0

        for i, chunk in enumerate(chunks):
            resp = await self.synthesize(
                text=chunk,
                voice_type=voice_type,
                speed=speed,
                pitch=pitch,
            )
            if not resp.success:
                return resp

            all_audio.extend(resp.audio_data or b"")
            total_latency += resp.latency_s

            if chunk_callback:
                await chunk_callback(i, len(chunks), resp.audio_data)

        audio_hash = _sha256_bytes(all_audio)
        duration_s = len(all_audio) / (2 * 24000)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(all_audio)

        return VolcanoTTSResponse(
            success=True,
            audio_data=bytes(all_audio),
            audio_hash=audio_hash,
            duration_s=duration_s,
            request_id=uuid.uuid4().hex[:16],
            latency_s=total_latency,
        )

    def _split_text(self, text: str, max_len: int = 500) -> list[str]:
        import re
        sentences = re.split(r'(?<=[。！？.!?])\s*', text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) <= max_len:
                current += sent
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)
        return chunks


def create_voice_performance(
    content_id: str,
    voice_profile: VoiceProfile,
    script_revision: int,
    response: VolcanoTTSResponse,
    output_path: Path,
    script_chars: int,
) -> VoicePerformance:
    actual_cps = script_chars / response.duration_s if response.duration_s > 0 else 0.0

    return VoicePerformance(
        performance_id=f"vp-{uuid.uuid4().hex[:8]}",
        content_id=content_id,
        voice_profile_id=voice_profile.voice_profile_id,
        script_revision=script_revision,
        audio_path=str(output_path),
        audio_hash=response.audio_hash,
        duration_s=response.duration_s,
        actual_chars_per_second=actual_cps,
        provider_request_id=response.request_id,
        provider_latency_s=response.latency_s,
        cost_usd=0.001 * response.duration_s,
        asr_aligned=False,
        asr_coverage=0.0,
    )


async def run_volcano_tts_qualification() -> dict[str, Any]:
    adapter = VolcanoTTSAdapter()

    if not adapter.config.app_id or not adapter.config.access_token:
        return {
            "success": False,
            "error": "VOLCANO_TTS_APP_ID and VOLCANO_TTS_ACCESS_TOKEN required",
            "qualified": False,
        }

    test_text = (
        "《沉思录》是马可·奥勒留留给后世的精神遗产。"
        "书中写道：你要为你的思想负责，因为思想决定你的命运。"
        "当我们在孤独中寻找答案时，这本书教会我们向内求索。"
    )

    output_path = Path("/tmp/volcano_qual_test.wav")
    response = await adapter.synthesize(
        text=test_text,
        output_path=output_path,
    )

    if not response.success:
        return {
            "success": False,
            "error": response.error,
            "qualified": False,
        }

    if not output_path.exists() or output_path.stat().st_size == 0:
        return {
            "success": False,
            "error": "Audio file not created",
            "qualified": False,
        }

    profile = VoiceProfile(
        voice_profile_id="volcano_bv001",
        provider="volcano",
        provider_voice_id="BV001_streaming",
        language="zh-CN",
    )

    performance = create_voice_performance(
        content_id="qual-test",
        voice_profile=profile,
        script_revision=1,
        response=response,
        output_path=output_path,
        script_chars=len(test_text),
    )

    pacing_ok = validate_voice_pacing(performance)

    return {
        "success": True,
        "qualified": pacing_ok,
        "audio_path": str(output_path),
        "audio_hash": response.audio_hash,
        "duration_s": response.duration_s,
        "actual_chars_per_second": performance.actual_chars_per_second,
        "pacing_ok": pacing_ok,
        "provider_latency_s": response.latency_s,
    }


__all__ = [
    "VolcanoTTSConfig",
    "VolcanoTTSRequest",
    "VolcanoTTSResponse",
    "VolcanoTTSAdapter",
    "create_voice_performance",
    "run_volcano_tts_qualification",
]