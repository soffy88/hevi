"""HEVI's existing LLM boundary for a local/private OpenAI-compatible proxy."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httpx


def _base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL", "").strip() or os.getenv("LONGCAT_BASE_URL", "").strip()).rstrip("/")


def _model() -> str:
    return os.getenv("OPENAI_MODEL", "").strip() or os.getenv("LONGCAT_MODEL", "").strip()


def _api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("LONGCAT_API_KEY", "").strip()


def _trusted_local() -> bool:
    return (urlsplit(_base_url()).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


async def _call(**payload: Any) -> dict[str, Any]:
    base = _base_url()
    model = _model()
    if not base or not model:
        raise RuntimeError("local OpenAI-compatible endpoint/model is not configured")
    key = _api_key()
    if not key and not _trusted_local():
        raise RuntimeError("public OpenAI-compatible endpoint requires authentication")
    body = dict(payload)
    body.setdefault("model", model)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI-compatible response has no choices")
    content = (choices[0].get("message") or {}).get("content")
    if not str(content or "").strip():
        raise RuntimeError("OpenAI-compatible response has empty content")
    return {"content": str(content), "usage": data.get("usage", {}), "request_id": data.get("id")}


def register_openai_compatible_llm() -> None:
    from obase.provider_registry import ProviderRegistry

    ProviderRegistry.register("llm", "openai_compatible", _call, replace=True)
    ProviderRegistry.register("llm", "default", _call, replace=True)


__all__ = ["register_openai_compatible_llm"]
