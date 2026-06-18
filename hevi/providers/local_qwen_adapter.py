"""Local Qwen LLM adapter — routes LLM calls to ollama OpenAI-compatible endpoint.

Registered as "llm"/"local" when HEVI_LLM_PROVIDER=qwen_local is set.
True async: httpx.AsyncClient, non-blocking, returns a plain dict.
oskill storyboard_planner/script_writer: result = await llm(messages=...)
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
_TIMEOUT = 600.0


def _coerce(obj: Any) -> Any:
    if isinstance(obj, dict):
        res: dict[str, Any] = {}
        for k, v in obj.items():
            if (k.endswith("_id") or k == "id") and isinstance(v, (int, float)):
                res[k] = str(v)
            elif k in ("importance", "index", "scene_index"):
                if isinstance(v, (int, float)):
                    res[k] = int(round(v))
                elif isinstance(v, str):
                    res[k] = {"low": 1, "minor": 1, "medium": 2, "normal": 2,
                               "high": 3, "major": 3, "critical": 4}.get(v.lower(), 0)
                else:
                    res[k] = 0
            elif k in ("scenes", "shots") and isinstance(v, list):
                fld = "visual_description" if k == "scenes" else "narration"
                res[k] = [
                    {"id": str(i + 1), fld: item} if isinstance(item, str)
                    else _coerce(item)
                    for i, item in enumerate(v)
                ]
            elif v is None:
                res[k] = ""
            else:
                res[k] = _coerce(v)
        return res
    elif isinstance(obj, list):
        return [_coerce(i) for i in obj]
    elif obj is None:
        return ""
    return obj


def _extract_content(raw: str) -> str:
    """Strip think blocks, extract JSON, coerce types."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    if not text:
        think_match = re.search(r"<think>(.*?)</think>", raw, flags=re.DOTALL)
        if think_match:
            text = think_match.group(1).strip()
            logger.debug("LocalQwenAdapter: extracted content from think block")

    try:
        clean = text.strip()
        if clean.startswith("```"):
            m = re.search(r"```(?:json)?\n?(.*?)\n?```", clean, re.DOTALL)
            if m:
                clean = m.group(1).strip()
        match = re.search(r"(\{.*\}|\[.*\])", clean, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            text = json.dumps(_coerce(data), ensure_ascii=False)
    except Exception as e:
        logger.debug("LocalQwenAdapter coercion skipped: %s", e)

    return text


async def local_qwen_adapter(**kwargs: Any) -> dict[str, Any]:
    """Async LLM adapter backed by ollama (qwen3.5:9b).

    Returns a plain dict: {"content": str, "output": {...}, "usage": {...}}
    Compatible with oskill's `result = await llm(messages=...)` protocol.
    """
    kwargs.pop("result_format", None)
    payload = {
        "model": _OLLAMA_MODEL,
        "messages": kwargs.get("messages", []),
        "max_tokens": kwargs.get("max_tokens", 4096),
        "temperature": kwargs.get("temperature", 0.7),
        "stream": False,
        "think": False,
    }

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{_OLLAMA_BASE}/v1/chat/completions", json=payload)
    r.raise_for_status()
    data = r.json()

    oa_choices = data.get("choices", [])
    native_choices = [
        {"message": c.get("message", {}), "finish_reason": c.get("finish_reason", "")}
        for c in oa_choices
    ]
    resp: dict[str, Any] = {
        "output": {"choices": native_choices},
        "usage": data.get("usage", {}),
        "content": "",
    }

    if oa_choices:
        raw = oa_choices[0].get("message", {}).get("content", "")
        resp["content"] = _extract_content(raw)

    return resp


def register_if_local() -> bool:
    """Register local_qwen_adapter as "llm"/"local" (always) and as "llm"/"default"
    when HEVI_LLM_PROVIDER=qwen_local. Returns True if default was overridden."""
    from obase.provider_registry import ProviderRegistry

    ProviderRegistry.register("llm", "local", local_qwen_adapter, replace=True)

    if os.getenv("HEVI_LLM_PROVIDER") == "qwen_local":
        ProviderRegistry.register("llm", "default", local_qwen_adapter, replace=True)
        logger.info("LLM provider: local_qwen_adapter (qwen3.5:9b via ollama)")
        return True
    return False
