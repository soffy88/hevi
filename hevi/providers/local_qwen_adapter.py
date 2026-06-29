"""Local Qwen LLM adapter — routes LLM calls to ollama OpenAI-compatible endpoint.

Registered as "llm"/"local" when HEVI_LLM_PROVIDER=qwen_local is set.
Uses sync httpx (run via asyncio.to_thread) to support both oskill calling conventions:
  sync:  result = llm(messages=...); result.get("content")   (storyboard_planner)
  async: result = await llm(messages=...); result.get("content")
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# qwen2.5:7b(非 thinking)与 deploy compose 一致;qwen3.5:9b 是 thinking 模型,
# 其推理 token 会吃光 max_tokens=2048 预算导致 content 为空(剧本阶段直接崩)。
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
_TIMEOUT = 300.0  # 120s for own generation + 180s queue wait behind AII


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
            candidate = match.group(1)
            # 本地模型(qwen2.5)常输出非严格 JSON:行内 // 注释、/* */ 块注释、尾逗号。
            # vendored oskill(select_reference/script_writer)用严格 json.loads,会崩。
            # 在此清洗成严格 JSON;(?<!:) 负向后顾保护 https:// 之类 URL。
            candidate = re.sub(r"/\*.*?\*/", "", candidate, flags=re.DOTALL)
            candidate = re.sub(r"(?<!:)//[^\n]*", "", candidate)
            candidate = re.sub(r",(\s*[}\]])", r"\1", candidate)
            data = json.loads(candidate)
            text = json.dumps(_coerce(data), ensure_ascii=False)
    except Exception as e:
        logger.debug("LocalQwenAdapter coercion skipped: %s", e)

    return text


def _call_ollama(**kwargs: Any) -> dict[str, Any]:
    """Sync HTTP call to Ollama. Safe to run in a thread (not on event loop)."""
    kwargs.pop("result_format", None)
    kwargs.pop("image_paths", None)  # VLM images not supported by text qwen
    payload = {
        "model": _OLLAMA_MODEL,
        "messages": kwargs.get("messages", []),
        # 2048 cap: storyboard needs ~1000 tokens; select_reference/consistency only ~50.
        # qwen2.5:7b at ~50 tok/s → 2048 tokens ≈ 41s, well within _TIMEOUT=300s.
        "max_tokens": kwargs.get("max_tokens", 2048),
        "temperature": kwargs.get("temperature", 0.7),
        "stream": False,
    }
    r = httpx.post(f"{_OLLAMA_BASE}/v1/chat/completions", json=payload, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # Unload model immediately after each call so Wan2GP (5407 MB) can use the GPU.
    # qwen2.5:7b + Wan2GP = 10155 MB vs 10240 MB total — can't coexist with KV cache.
    try:
        httpx.post(
            f"{_OLLAMA_BASE}/api/generate",
            json={"model": _OLLAMA_MODEL, "keep_alive": 0},
            timeout=5.0,
        )
    except Exception:
        pass  # best-effort unload

    oa_choices = data.get("choices", [])
    native_choices = [
        {"message": c.get("message", {}), "finish_reason": c.get("finish_reason", "")}
        for c in oa_choices
    ]
    content = ""
    if oa_choices:
        raw = oa_choices[0].get("message", {}).get("content", "")
        content = _extract_content(raw)

    return {
        "output": {"choices": native_choices},
        "usage": data.get("usage", {}),
        "content": content,
    }


class LocalQwenAdapter:
    """Sync-callable LLM adapter with async protocol — mirrors AsyncDashScopeAdapter.

    oskill calling conventions supported:
      sync:  result = llm(messages=...); result.get("content")
      async: result = await llm(messages=...); result.get("content")

    When called in sync context (storyboard_planner), _call_ollama runs directly.
    When awaited, it runs in asyncio.to_thread so the event loop stays free.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._resp: dict[str, Any] | None = None

    def _ensure_resp(self) -> dict[str, Any]:
        if self._resp is None:
            self._resp = _call_ollama(**self._kwargs)
        return self._resp

    def get(self, key: str, default: Any = None) -> Any:
        return self._ensure_resp().get(key, default)

    def __await__(self) -> Any:
        async def _run() -> dict[str, Any]:
            if self._resp is not None:
                return self._resp
            fn = functools.partial(_call_ollama, **self._kwargs)
            self._resp = await asyncio.to_thread(fn)
            return self._resp
        return _run().__await__()


def local_qwen_adapter(**kwargs: Any) -> LocalQwenAdapter:
    """Factory that returns a LocalQwenAdapter (sync-callable + awaitable)."""
    return LocalQwenAdapter(**kwargs)


def register_if_local() -> bool:
    """Register local_qwen_adapter as "llm"/"local" (always) and as "llm"/"default"
    when HEVI_LLM_PROVIDER=qwen_local. Returns True if default was overridden."""
    from obase.provider_registry import ProviderRegistry

    ProviderRegistry.register("llm", "local", local_qwen_adapter, replace=True)

    if os.getenv("HEVI_LLM_PROVIDER") == "qwen_local":
        ProviderRegistry.register("llm", "default", local_qwen_adapter, replace=True)
        logger.info("LLM provider: local_qwen_adapter (%s via ollama)", _OLLAMA_MODEL)
        return True
    return False
