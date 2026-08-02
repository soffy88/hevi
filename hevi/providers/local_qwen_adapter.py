"""Local Qwen LLM adapter — routes LLM calls to ollama OpenAI-compatible endpoint.

Registered as "llm"/"local" when HEVI_LLM_PROVIDER=qwen_local is set.
Uses sync httpx (run via asyncio.to_thread) to support both oskill calling conventions:
  sync:  result = llm(messages=...); result.get("content")   (storyboard_planner)
  async: result = await llm(messages=...); result.get("content")
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# qwen3 等 thinking 模型在当前 OpenAI 兼容适配器下可能把预算耗在 reasoning,
# 导致 content 为空。qwen2.5vl 是当前部署已验证的非 thinking 兼容模型。
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")
_OLLAMA_FALLBACK_MODELS = ("qwen2.5vl:7b", "llama3.2:latest")
_TIMEOUT = 300.0  # 120s for own generation + 180s queue wait behind AII


def _available_models() -> set[str]:
    """Read Ollama's model inventory without making generation calls."""
    try:
        response = httpx.get(f"{_OLLAMA_BASE}/api/tags", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        return {
            str(item.get("name") or item.get("model"))
            for item in payload.get("models", [])
            if isinstance(item, dict) and (item.get("name") or item.get("model"))
        }
    except Exception as exc:
        # Keep the configured model as the last resort. The generation request
        # will produce a precise error if Ollama itself is unavailable.
        logger.warning("无法读取 Ollama 模型清单(%s): %s", _OLLAMA_BASE, exc)
        return set()


def _resolve_model() -> str:
    """Choose a configured model that actually exists on the Ollama host."""
    available = _available_models()
    if not available:
        return _OLLAMA_MODEL
    if _OLLAMA_MODEL in available:
        return _OLLAMA_MODEL
    for candidate in _OLLAMA_FALLBACK_MODELS:
        if candidate in available:
            logger.warning(
                "配置的 Ollama 模型 %s 不存在,自动回退到 %s", _OLLAMA_MODEL, candidate
            )
            return candidate
    raise RuntimeError(
        f"Ollama 模型不可用: {_OLLAMA_MODEL}; 当前可用模型: {sorted(available)}"
    )


def _coerce(obj: Any) -> Any:
    if isinstance(obj, dict):
        res: dict[str, Any] = {}
        for k, v in obj.items():
            if (k.endswith("_id") or k == "id") and isinstance(v, (int, float)):
                res[k] = str(v)
            elif k in ("importance", "index", "scene_index"):
                if isinstance(v, (int, float)):
                    res[k] = round(v)
                elif isinstance(v, str):
                    res[k] = {
                        "low": 1,
                        "minor": 1,
                        "medium": 2,
                        "normal": 2,
                        "high": 3,
                        "major": 3,
                        "critical": 4,
                    }.get(v.lower(), 0)
                else:
                    res[k] = 0
            elif k in ("scenes", "shots") and isinstance(v, list):
                fld = "visual_description" if k == "scenes" else "narration"
                res[k] = [
                    {"id": str(i + 1), fld: item} if isinstance(item, str) else _coerce(item)
                    for i, item in enumerate(v)
                ]
            elif v is None:
                res[k] = ""
            else:
                res[k] = _coerce(v)
        return res
    if isinstance(obj, list):
        return [_coerce(i) for i in obj]
    if obj is None:
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
    result_format = kwargs.pop("result_format", None)
    kwargs.pop("image_paths", None)  # VLM images not supported by text qwen
    model = _resolve_model()
    payload = {
        "model": model,
        "messages": kwargs.get("messages", []),
        # 2048 cap: storyboard needs ~1000 tokens; select_reference/consistency only ~50.
        "max_tokens": kwargs.get("max_tokens", 2048),
        "temperature": kwargs.get("temperature", 0.7),
        "stream": False,
    }
    if result_format in ("json", "json_object"):
        payload["response_format"] = {"type": "json_object"}
    # SaaS-4 Fix: ollama 在模型冷加载 / keep_alive:0 卸载切换的窗口内会对紧接的
    # 下一次请求返回瞬时 500(顺序流水线里每次调用后都卸载,下一镜头的 select_
    # reference 极易撞上)。这类错误可重试即恢复;不重试则整任务失败。对 500/502/
    # 503 与连接错误做指数退避重试,其它错误(如 4xx)立即抛出。
    import time as _time

    last_exc: Exception | None = None
    data: dict[str, Any] = {}
    for _attempt in range(4):
        try:
            r = httpx.post(f"{_OLLAMA_BASE}/v1/chat/completions", json=payload, timeout=_TIMEOUT)
            if r.status_code in (500, 502, 503):
                raise httpx.HTTPStatusError(
                    f"ollama transient {r.status_code}", request=r.request, response=r
                )
            r.raise_for_status()
            data = r.json()
            break
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            # 4xx(非上面几个)不重试
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code == 404:
                raise RuntimeError(f"Ollama 模型不可用: {model}") from exc
            if resp is not None and resp.status_code not in (500, 502, 503):
                raise
            last_exc = exc
            if _attempt < 3:
                _time.sleep(1.5 * (_attempt + 1))  # 1.5s, 3s, 4.5s
                logger.warning("ollama transient error, retry %d/3: %s", _attempt + 1, exc)
    else:
        raise last_exc if last_exc else RuntimeError("ollama call failed")
    # Unload model immediately after each call so Wan2GP (5407 MB) can use the GPU.
    # qwen2.5:7b + Wan2GP = 10155 MB vs 10240 MB total — can't coexist with KV cache.
    with contextlib.suppress(Exception):  # best-effort unload
        httpx.post(
            f"{_OLLAMA_BASE}/api/generate",
            json={"model": model, "keep_alive": 0},
            timeout=5.0,
        )

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
        "model": model,
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
    unless the operator explicitly opts back into cloud DashScope.

    SaaS-4 决策(长期主义):DashScope 账号已欠费停用(compat 端点返回 Arrearage),
    走它的 LLM 通道必崩。因此本地 ollama qwen 设为**默认** LLM,任何环境(含未设
    .env 的 host 实例)开箱即用;仅当显式 `HEVI_LLM_PROVIDER=dashscope` 时才回退云。
    Returns True if local was installed as the default.
    """
    from obase.provider_registry import ProviderRegistry

    ProviderRegistry.register("llm", "local", local_qwen_adapter, replace=True)

    # 默认本地;仅显式 dashscope 才用云(欠费恢复后可临时切回)。
    if os.getenv("HEVI_LLM_PROVIDER", "qwen_local") != "dashscope":
        ProviderRegistry.register("llm", "default", local_qwen_adapter, replace=True)
        logger.info("LLM provider: local_qwen_adapter (%s via ollama)", _OLLAMA_MODEL)
        return True
    logger.info("LLM provider: DashScope (explicit HEVI_LLM_PROVIDER=dashscope)")
    return False
