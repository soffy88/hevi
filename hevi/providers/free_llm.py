"""免费/本地文本 LLM 通道解析（DRAMAPLAN）。

短剧/漫剧的**规划层**（storygraph 抽取、season_planner 分集、三层审稿）全部是文本 LLM
工作。本模块提供一个显式的 `llm_channel` 解析器：只走免费/本地通道，绝不落到付费
DashScope（`qwen_cloud`）。

通道优先级（`auto`）：
  1. ``omniroute_free``  本机 omniroute（:20128，只选标 free 的模型）
  2. ``nim``             NVIDIA NIM 免费层（HEVI_NIM_KEYS / 密钥池）
  3. ``opencode``        OpenCode 免费模型（OPENCODE_API_KEY）
  4. ``teamo_free``      TeamoRouter 免费福利模型（TEAMOROUTER_API_KEY）
  5. ``ollama``          本机 ollama（离线兜底，质量差）
  6. ``default``         仓库既有 default（可能是本地 adapter；最后兜底）

设计约束：
- 不 import torch/diffusers（重依赖不得在策略路径加载）。
- 每个通道构造失败（无 key / 无 base_url）返回 ``None``，由 `resolve_free_llm` 顺延，
  不抛异常；调用方仍可对单次调用失败自行降级。
- 返回的 caller 是 async 可调用，返回 ``{"content": "<text>"}``（同仓库既有 LLM 约定）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 免费通道优先序。实测（见 scripts/dramaplan/llm_channel_probe.py 与 DONE）：NIM 免费层
# 稳定（~1.5s、JSON 干净），omniroute auto/* 实测超时、oc/* 需 key，opencode 需 session
# 头，teamo TCP 不通，ollama 可但慢。故 auto 首选 NIM；``default`` 放最后（可能被部署
# 配成付费端点，短剧规划默认不选它）。
FREE_CHANNEL_ORDER: tuple[str, ...] = (
    "nim",
    "omniroute_free",
    "opencode",
    "teamo_free",
    "ollama",
    "default",
)

_OMNIROUTE_DEFAULT_BASE = "http://127.0.0.1:20128/v1"
_OMNIROUTE_DEFAULT_MODEL = "auto/coding:free"
_OLLAMA_DEFAULT_BASE = "http://127.0.0.1:11434/v1"
_OLLAMA_DEFAULT_MODEL = "llama3.2:3b"


def _openai_compatible_caller(
    *,
    channel: str,
    base_url: str,
    model: str,
    api_key: str = "",
    timeout: float = 120.0,
    temperature: float | None = None,
) -> Any:
    """构造一个 OpenAI 兼容 chat/completions 的 async caller。"""

    async def _call(
        *,
        messages: list[dict[str, str]] | None = None,
        max_tokens: int = 4096,
        system: str = "",
        temperature_override: float | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        import httpx

        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages or [])
        payload: dict[str, Any] = {
            "model": model,
            "messages": payload_messages,
            "max_tokens": max_tokens,
        }
        temp = temperature_override if temperature_override is not None else temperature
        if temp is not None:
            payload["temperature"] = temp
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        url = f"{base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"{channel}: response missing choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            content = message.get("reasoning") or ""
        if not content:
            raise RuntimeError(f"{channel}: empty content")
        return {"content": str(content)}

    return _call


def _build_omniroute() -> Any | None:
    base = os.getenv("OMNIROUTE_BASE_URL", _OMNIROUTE_DEFAULT_BASE).strip()
    if not base:
        return None
    return _openai_compatible_caller(
        channel="omniroute_free",
        base_url=base,
        model=os.getenv("OMNIROUTE_MODEL", _OMNIROUTE_DEFAULT_MODEL),
        api_key=os.getenv("OMNIROUTE_API_KEY", "").strip(),
        timeout=float(os.getenv("OMNIROUTE_TIMEOUT_S", "120")),
    )


def _build_nim() -> Any | None:
    try:
        from hevi.providers.nim_caller import DEFAULT_NIM_MODEL, _make_nim_caller, _nim_keys
    except Exception:  # pragma: no cover - import guard
        return None
    keys = _nim_keys()
    if not keys:
        return None
    model = os.getenv("HEVI_NIM_MODEL", DEFAULT_NIM_MODEL)
    # reasoning 模型(nemotron-3-super 等)会把大量 token 花在 reasoning_content,
    # 结构化 JSON 任务里常常 reasoning 吃光 max_tokens 导致 content 为空。默认关掉
    # thinking(实测 0.7s 返回干净 JSON);HEVI_NIM_THINKING=1 可恢复。
    extra_body: dict[str, Any] = {}
    if os.getenv("HEVI_NIM_THINKING", "0").strip() not in ("1", "true", "True"):
        extra_body["chat_template_kwargs"] = {"thinking": False}
    try:
        return _make_nim_caller(
            keys,
            model=model,
            timeout=float(os.getenv("HEVI_NIM_TIMEOUT", "60")),
            extra_body=extra_body or None,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("nim 通道构造失败: %s", exc)
        return None


def _build_opencode() -> Any | None:
    key = os.getenv("OPENCODE_API_KEY", "").strip()
    if not key:
        return None
    base = os.getenv("OPENCODE_BASE_URL", "https://api.opencode.ai/v1").strip()
    return _openai_compatible_caller(
        channel="opencode",
        base_url=base,
        model=os.getenv("OPENCODE_MODEL", "hy3"),
        api_key=key,
        timeout=float(os.getenv("OPENCODE_TIMEOUT_S", "120")),
    )


def _build_teamo_free() -> Any | None:
    key = os.getenv("TEAMOROUTER_API_KEY", "").strip()
    if not key:
        return None
    base = os.getenv("TEAMOROUTER_BASE_URL", "https://api.teamorouter.com/v1").strip()
    return _openai_compatible_caller(
        channel="teamo_free",
        base_url=base,
        model=os.getenv("TEAMOROUTER_FREE_MODEL", "deepseek-v4-flash-free"),
        api_key=key,
        timeout=float(os.getenv("TEAMOROUTER_TIMEOUT_S", "120")),
    )


def _build_ollama() -> Any | None:
    base = os.getenv("OLLAMA_BASE_URL", _OLLAMA_DEFAULT_BASE).strip()
    if not base:
        return None
    return _openai_compatible_caller(
        channel="ollama",
        base_url=base,
        model=os.getenv("OLLAMA_MODEL", _OLLAMA_DEFAULT_MODEL),
        timeout=float(os.getenv("OLLAMA_TIMEOUT_S", "300")),
    )


def _build_default() -> Any | None:
    try:
        from obase.provider_registry import ProviderRegistry

        return ProviderRegistry.get().llm("default")
    except Exception:
        return None


_BUILDERS = {
    "omniroute_free": _build_omniroute,
    "nim": _build_nim,
    "opencode": _build_opencode,
    "teamo_free": _build_teamo_free,
    "ollama": _build_ollama,
    "default": _build_default,
}


def available_channels() -> list[str]:
    """返回当前环境里构造得出的通道名（不发起网络请求）。"""
    return [name for name in FREE_CHANNEL_ORDER if _BUILDERS[name]() is not None]


def build_channel_caller(channel: str) -> Any | None:
    """按显式通道名构造 caller；未知通道或构造失败返回 None。"""
    builder = _BUILDERS.get(channel)
    return builder() if builder else None


def resolve_free_llm(channel: str | None = None) -> tuple[str, Any]:
    """解析免费文本 LLM。

    Args:
        channel: 显式通道名，或 ``None``/``"auto"`` 走 `FREE_CHANNEL_ORDER`。

    Returns:
        ``(channel_name, caller)``。全部不可用时抛 ``RuntimeError``（规划层应据此
        走确定性规则兜底，而不是静默无 LLM 继续）。

    Raises:
        ValueError: 显式指定的通道不可用。
        RuntimeError: auto 下没有任何免费通道可用。
    """
    if channel and channel != "auto":
        caller = build_channel_caller(channel)
        if caller is None:
            raise ValueError(f"llm_channel {channel!r} 不可用（缺 key/端点或未注册）")
        return channel, caller

    for name in FREE_CHANNEL_ORDER:
        caller = _BUILDERS[name]()
        if caller is not None:
            return name, caller
    raise RuntimeError(
        "没有任何免费 LLM 通道可用；短剧规划请走确定性规则兜底或配置 HEVI_NIM_KEYS"
    )


async def probe_channel(channel: str, *, timeout: float = 90.0) -> dict[str, Any]:
    """真实调用一次通道，记录可用性/延迟/JSON 稳定性（供探测脚本用）。"""
    import time

    caller = build_channel_caller(channel)
    if caller is None:
        return {"channel": channel, "available": False, "reason": "not_configured"}
    prompt = '只输出一个 JSON 对象，不要任何其它文字：{"ok": true, "n": 3}'
    start = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            caller(messages=[{"role": "user", "content": prompt}], max_tokens=64),
            timeout=timeout,
        )
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        latency = round(time.monotonic() - start, 2)
        json_ok = False
        try:
            parsed = json.loads(str(content).strip())
            json_ok = parsed.get("ok") is True and parsed.get("n") == 3
        except Exception:
            json_ok = False
        return {
            "channel": channel,
            "available": True,
            "latency_s": latency,
            "json_stable": json_ok,
            "content_head": str(content)[:120],
        }
    except Exception as exc:
        return {
            "channel": channel,
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            "latency_s": round(time.monotonic() - start, 2),
        }


__all__ = [
    "FREE_CHANNEL_ORDER",
    "available_channels",
    "build_channel_caller",
    "probe_channel",
    "resolve_free_llm",
]
