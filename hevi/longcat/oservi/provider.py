"""HTTP adapter for a LongCat/vLLM OpenAI-compatible endpoint.

No LongCat package or checkpoint is installed by HEVI.  A local GPU/NPU
server can be pointed at this adapter with ``LONGCAT_BASE_URL``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


def _base_url() -> str:
    return os.getenv("LONGCAT_BASE_URL", "").strip().rstrip("/")


def longcat_provider_status() -> dict[str, Any]:
    base_url = _base_url()
    return {
        "configured": bool(base_url),
        "available": bool(base_url),
        "status": "configured" if base_url else "unconfigured",
        "base_url": base_url or None,
        "model": os.getenv("LONGCAT_MODEL", "LongCat-2.0").strip() or "LongCat-2.0",
        "device": os.getenv("LONGCAT_DEVICE", "auto").strip() or "auto",
        "streaming": True,
        "setup": "配置 LONGCAT_BASE_URL 指向 /v1 的 OpenAI-compatible chat 服务；权重由服务端管理。",
    }


@dataclass
class LongCatProvider:
    base_url: str
    api_key: str = ""
    timeout_s: float = 600.0

    async def __call__(self, **payload: Any) -> dict[str, Any]:
        body = dict(payload)
        body.setdefault("model", os.getenv("LONGCAT_MODEL", "LongCat-2.0"))
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("LongCat provider returned a non-object response")
        return data

    async def stream(self, **payload: Any) -> AsyncIterator[dict[str, Any]]:
        """Yield OpenAI-compatible SSE chunks without buffering the response."""

        body = dict(payload)
        body.setdefault("model", os.getenv("LONGCAT_MODEL", "LongCat-2.0"))
        body["stream"] = True
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client, client.stream(
                "POST",
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    break
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict):
                    yield chunk


def build_longcat_caller() -> LongCatProvider | None:
    base_url = _base_url()
    if not base_url:
        return None
    return LongCatProvider(
        base_url=base_url,
        api_key=os.getenv("LONGCAT_API_KEY", "").strip(),
        timeout_s=float(os.getenv("LONGCAT_TIMEOUT_S", "600")),
    )


__all__ = ["LongCatProvider", "build_longcat_caller", "longcat_provider_status"]
