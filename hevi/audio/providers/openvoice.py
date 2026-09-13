"""HTTP adapter for an isolated OpenVoice service.

No OpenVoice package is imported here.  The model runtime remains outside the
HEVI environment and is never treated as a default or fallback provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import httpx


class OpenVoiceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenVoiceCapabilities:
    text_to_speech: bool = True
    voice_clone: bool = True
    tone_color_transfer: bool = True
    cross_lingual_voice: bool = True
    supported_languages: tuple[str, ...] = ("en", "zh", "ja", "ko")
    reference_audio_required: bool = True


@dataclass(frozen=True)
class OpenVoiceResult:
    artifact: Path
    duration_s: float
    sample_rate: int
    provider: str
    model: str
    reference_sha256: str | None
    generation_parameters: dict[str, Any]


class OpenVoiceProvider:
    name = "openvoice"
    license_metadata: ClassVar[dict[str, object]] = {
        "provider": "openvoice",
        "license": "MIT (upstream code; model/license must be verified per deployment)",
        "bundled": False,
        "optional": True,
        "commercial_review_required": True,
    }

    def __init__(self, *, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        configured_url = base_url if base_url is not None else os.getenv("OPENVOICE_SERVICE_URL", "")
        self.base_url = (configured_url or "").rstrip("/")
        self.client = client
        self.capabilities = OpenVoiceCapabilities()

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    async def readiness(self) -> dict[str, Any]:
        if not self.configured:
            return {"status": "BLOCKED_SERVICE", "blocker": "OPENVOICE_SERVICE_URL missing"}
        try:
            response = await self._request("GET", "/health")
            if response.status_code >= 400:
                return {"status": "BLOCKED_SERVICE", "blocker": f"HTTP_{response.status_code}"}
            payload = response.json()
            status = str(payload.get("status", "BLOCKED_SERVICE"))
            return {"status": status if status.startswith("BLOCKED_") else ("READY" if status in {"ok", "ready", "healthy", "READY"} else "BLOCKED_SERVICE"), "model": payload.get("model"), **({"reason": payload["reason"]} if payload.get("reason") else {})}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "BLOCKED_NETWORK", "blocker": type(exc).__name__}

    async def synthesize(self, *, text: str, language: str, output_path: Path, reference_audio: Path, options: dict[str, Any] | None = None) -> OpenVoiceResult:
        if not self.configured:
            raise OpenVoiceUnavailable("OPENVOICE_SERVICE_URL missing")
        if not reference_audio.is_file() or reference_audio.stat().st_size == 0:
            raise OpenVoiceUnavailable("reference audio missing or empty")
        payload: dict[str, Any] = {"text": text, "language": language, "options": options or {}, "reference_sha256": _sha256(reference_audio)}
        response = await self._request("POST", "/v1/synthesize", json=payload)
        if response.status_code == 429:
            raise OpenVoiceUnavailable("RATE_LIMITED")
        if response.status_code >= 400:
            raise OpenVoiceUnavailable(f"UPSTREAM_FAILURE:HTTP_{response.status_code}")
        data = response.json()
        artifact_url = data.get("artifact_url")
        if not artifact_url:
            raise OpenVoiceUnavailable("INVALID_RESPONSE:artifact_url missing")
        artifact_response = await self._request("GET", artifact_url)
        artifact_response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(artifact_response.content)
        if output_path.stat().st_size == 0:
            raise OpenVoiceUnavailable("INVALID_OUTPUT:empty audio")
        media = _probe_audio(output_path)
        return OpenVoiceResult(output_path, float(media["duration_s"]), int(media["sample_rate"]), self.name, str(data.get("model", "unknown")), str(payload["reference_sha256"]), options or {})

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        if self.client is not None:
            return await self.client.request(method, url, timeout=30.0, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, timeout=30.0, **kwargs)


async def openvoice_synthesize(**kwargs: Any) -> OpenVoiceResult:
    """ProviderRegistry-compatible adapter; unavailable means a real error."""
    return await OpenVoiceProvider().synthesize(**kwargs)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_audio(path: Path) -> dict[str, int | float | str]:
    if shutil.which("ffprobe") is None:
        raise OpenVoiceUnavailable("INVALID_OUTPUT:ffprobe unavailable")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=sample_rate,channels", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise OpenVoiceUnavailable("INVALID_OUTPUT:ffprobe failed")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OpenVoiceUnavailable("INVALID_OUTPUT:invalid audio metadata") from exc
    if duration <= 0 or sample_rate <= 0 or channels <= 0:
        raise OpenVoiceUnavailable("INVALID_OUTPUT:invalid audio dimensions")
    return {"duration_s": duration, "sample_rate": sample_rate, "channels": channels}
