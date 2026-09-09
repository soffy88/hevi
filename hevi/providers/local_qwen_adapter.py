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

from hevi.providers.reliability import (
    ProviderCallError,
    ProviderExecutionWrapper,
    RateLimitPolicy,
    ReliabilityConfig,
    RetryPolicy,
    TimeoutPolicy,
)

logger = logging.getLogger(__name__)

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# qwen3 等 thinking 模型在当前 OpenAI 兼容适配器下可能把预算耗在 reasoning,
# 导致 content 为空。qwen2.5vl 是当前部署已验证的非 thinking 兼容模型。
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")
# The host currently deploys the 3b VLM when the configured 7b model is not
# present. Keep both Qwen sizes ahead of the generic fallback so model
# inventory resolution does not prevent the generation retry policy from
# handling a transient chat 500.
_OLLAMA_FALLBACK_MODELS = ("qwen2.5vl:7b", "qwen2.5vl:3b", "llama3.2:latest")
_TIMEOUT = 30.0
_OLLAMA_WRAPPER = ProviderExecutionWrapper(
    "ollama",
    os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b"),
    config=ReliabilityConfig(
        timeout=TimeoutPolicy(connect_s=3.0, read_s=_TIMEOUT, write_s=10.0, pool_s=3.0, total_s=60.0),
        retry=RetryPolicy(max_attempts=3, base_backoff_s=0.25, max_backoff_s=2.0, jitter_ratio=0.25),
        max_concurrency=1,
        rate_limit=RateLimitPolicy(requests_per_minute=60.0, burst=4),
    ),
)


def _inventory_wrapper() -> ProviderExecutionWrapper:
    """Build an isolated bounded probe for the mutable local model inventory.

    Inventory is advisory and is re-read for every model resolution.  Keeping
    its breaker separate from generation prevents a daemon-startup probe from
    suppressing a later chat request, while every probe still has the common
    timeout/retry/metrics contract.
    """
    return ProviderExecutionWrapper(
        "ollama",
        os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b"),
        config=ReliabilityConfig(
            timeout=TimeoutPolicy(connect_s=3.0, read_s=3.0, write_s=3.0, pool_s=3.0, total_s=10.0),
            retry=RetryPolicy(max_attempts=3, base_backoff_s=0.25, max_backoff_s=2.0, jitter_ratio=0.25),
            max_concurrency=1,
            rate_limit=RateLimitPolicy(requests_per_minute=120.0, burst=4),
        ),
    )


def _available_models() -> set[str]:
    """Read Ollama's model inventory without making generation calls."""
    try:
        result = _inventory_wrapper().execute_sync(
            lambda: _tags_request(), idempotent=True, output_token_budget=0
        )
        payload = result.require_value()
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


def _tags_request() -> dict[str, Any]:
    response = httpx.get(f"{_OLLAMA_BASE}/api/tags", timeout=3.0)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Ollama model inventory is not an object")
    return payload


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


def _coerce_numeric_fields(obj: Any) -> Any:
    """把常见数字字段从字符串/空串规整成 float,防止下游 pydantic 报
    `Input should be a valid number, unable to parse string as number`。

    oskill 的 Shot.duration_s 是必填 float;本地 qwen2.5vl 在长上下文里常把
    duration_s / duration / start_s / end_s / total_duration_s 输出成空串或
    "5" 这类字符串,直接 json.loads 后 pydantic 校验崩。这里统一做一次深度
    清洗:数字型 key 一律转 float(空串/None → 0.0),不影响已是数字的值。
    """
    _NUMERIC_KEYS = {
        "duration_s",
        "duration",
        "start_s",
        "end_s",
        "source_in_s",
        "total_duration_s",
        "estimated_duration_s",
        "target_duration_s",
        "suggested_duration_s",
        "t_start_s",
        "t_end_s",
        "source_start_s",
        "source_end_s",
    }
    if isinstance(obj, dict):
        res: dict[str, Any] = {}
        for k, v in obj.items():
            if k in _NUMERIC_KEYS:
                if v is None or v == "":
                    res[k] = 0.0
                elif isinstance(v, (bool, int, float)):
                    res[k] = float(v)
                else:
                    try:
                        res[k] = float(str(v).strip())
                    except (ValueError, TypeError):
                        res[k] = 0.0
            else:
                res[k] = _coerce_numeric_fields(v)
        return res
    if isinstance(obj, list):
        return [_coerce_numeric_fields(i) for i in obj]
    return obj


def _repair_misplaced_top_level_keys(candidate: str, data: Any = None) -> Any:
    """宽容修复本地模型常见的 JSON 形状漂移:顶层键被误塞进最后一个元素。

    例(真实复现):模型把 total_duration_s/characters 作为 chapters 数组的最后一个
    元素输出(合法 JSON 但层级错误,或直接导致解析失败)。这里把**含顶层键**的
    dict 元素从 chapters 弹出来合并回顶层。candidate 仅在 data 未提供时解析。
    """
    if data is None:
        try:
            data = json.loads(candidate, strict=False)  # 允许字符串内换行/控制字符
        except json.JSONDecodeError:
            raise
    if not isinstance(data, dict):
        raise ValueError("not an object")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return data
    # 只认"决定性"顶层键:total_duration_s/characters/estimated_duration_s 几乎
    # 不可能出现在 chapter 对象里;title/description 是 chapter 常见字段,不能拿来判。
    top_keys = {"total_duration_s", "characters", "estimated_duration_s", "chapters"}
    repaired = [c for c in chapters if not (isinstance(c, dict) and any(k in c for k in top_keys))]
    for c in chapters:
        if isinstance(c, dict) and any(k in c for k in top_keys):
            for k, v in c.items():
                if k not in data:
                    data[k] = v
    data["chapters"] = repaired
    return data


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
            try:
                data = json.loads(candidate, strict=False)  # 允许字符串内换行/控制字符
                # 形状漂移修复(即使 JSON 合法也要做):本地模型常把顶层键
                # (total_duration_s/characters)误塞进最后一个 chapter 对象 —— 合法
                # JSON 但层级错误,下游 oskill 拿不到顶层字段。
                data = _repair_misplaced_top_level_keys(candidate, data=data)
            except json.JSONDecodeError:
                data = _repair_misplaced_top_level_keys(candidate)
            text = json.dumps(_coerce_numeric_fields(_coerce(data)), ensure_ascii=False)
    except Exception as e:
        logger.debug("LocalQwenAdapter coercion skipped: %s", e)

    return text


def _call_ollama(**kwargs: Any) -> dict[str, Any]:
    """Sync HTTP call to Ollama. Safe to run in a thread (not on event loop)."""
    kwargs.pop("result_format", None)
    kwargs.pop("image_paths", None)  # VLM images not supported by text qwen
    model = _resolve_model()
    payload = {
        "model": model,
        "messages": kwargs.get("messages", []),
        # chapter script(script_writer chapter_mode)需要 ~3000-4000 tokens 才能
        # 输出 2 章完整对白+场景;2048 会截断 → json.loads 崩("invalid JSON for
        # chapter script")。默认提到 4096,storyboard/审片等短任务仍可经 kwargs
        # 传小值覆盖。
        "max_tokens": kwargs.get("max_tokens", 4096),
        "temperature": kwargs.get("temperature", 0.7),
        "stream": False,
    }
    # 强制 JSON 模式:本地 qwen2.5vl 自由文本输出常带换行/缺逗号等畸形,oskill
    # 的 script_writer/storyboard_planner 并不传 result_format。Ollama 的
    # OpenAI 兼容端点支持 response_format=json_object,能显著降低畸形率。
    payload["response_format"] = {"type": "json_object"}
    def _chat_request() -> dict[str, Any]:
        response = httpx.post(
            f"{_OLLAMA_BASE}/v1/chat/completions",
            json=payload,
            timeout=_OLLAMA_WRAPPER.config.timeout.httpx_timeout,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Ollama completion is not an object")
        return data

    result = _OLLAMA_WRAPPER.execute_sync(
        _chat_request,
        idempotent=True,
        input_tokens=sum(len(str(message.get("content", ""))) for message in payload["messages"]),
        output_token_budget=int(payload["max_tokens"]),
    )
    try:
        data = result.require_value()
    except ProviderCallError as exc:
        if exc.error_class.value == "client_error":
            raise RuntimeError(f"Ollama 模型不可用: {model}") from exc
        raise
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
