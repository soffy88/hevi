"""OpenCode LLM provider(OpenAI 兼容, 替换 NIM 作为研究/创意默认)。

背景: 用户提供 OpenCode 服务的 sk- API key, 用于替换 NVIDIA NIM 承担
explainer research / MCP 创意工具的 LLM 推理。OpenCode 走 OpenAI 兼容
chat/completions 协议, 端点与模型全部环境变量驱动:

    OPENCODE_BASE_URL   OpenAI 兼容端点(默认 https://api.opencode.ai/v1)
    OPENCODE_API_KEY     sk- API key(必填才注册)
    OPENCODE_MODEL      模型名(默认见下)
    OPENCODE_TIMEOUT_S  超时秒(默认 600, 与 NIM 一致保长研究)

注册为 llm("opencode"); research._default_llm() 优先取它。未配置 key 时
静默跳过, 回落 NIM/default —— 替换可逆, 不破坏既有研究链路。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.opencode.ai/v1"
DEFAULT_MODEL = "hy3"


def _api_key() -> str:
    return os.getenv("OPENCODE_API_KEY", "").strip()


def _make_opencode_caller(
    api_key: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = 600.0,
) -> Any:
    """构造 OpenAI 兼容 chat/completions 异步 caller(LLMCaller 协议)。

    与 NIM caller 同构: system+messages 拼 user content, 返回 {"content": ...};
    model 参数由环境变量锁定(忽略调用方传入, 与 NIM 策略一致)。
    """

    async def _call(
        *,
        messages: list[dict[str, str]] | None = None,
        max_tokens: int = 4096,
        system: str = "",
        temperature: float | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        parts: list[str] = []
        if system:
            parts.append(system)
        parts.extend(
            str(msg.get("content", ""))
            for msg in messages or []
            if isinstance(msg, dict) and msg.get("role") == "user"
        )
        combined = "\n\n".join(p for p in parts if p)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": combined}],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        loop = asyncio.get_event_loop()

        def _blocking() -> str:
            with httpx.Client(trust_env=True, timeout=timeout) as client:
                response = client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                if response.status_code >= 400:
                    raise RuntimeError(
                        f"OpenCode HTTP {response.status_code}: {response.text[:300]}"
                    )
                try:
                    data = response.json()
                except ValueError as exc:
                    # 200 但非 JSON(如 Cloudflare "Not Found" 占位页) → 明确报错。
                    raise RuntimeError(
                        f"OpenCode 返回非 JSON 响应({response.text[:80]!r}); "
                        f"请检查 OPENCODE_BASE_URL={base_url} 是否为可用的 "
                        "OpenAI 兼容 chat/completions 端点。"
                    ) from exc
            choices = data.get("choices") or []
            if not choices:
                raise RuntimeError(f"OpenCode 响应缺 choices: {str(data)[:200]}")
            message = (choices[0].get("message") or {})
            content = message.get("content")
            if not content:
                # 推理模型(reasoning): content 可能为 null, 回退 reasoning 字段。
                content = message.get("reasoning") or ""
            if not content:
                raise RuntimeError("OpenCode 返回空 content")
            return str(content)

        text = await loop.run_in_executor(None, _blocking)
        return {"content": text}

    return _call


def register_opencode_llm() -> None:
    """注册 llm("opencode")。无 key 静默跳过(research 回落 NIM/default)。

    v9.1: 端点在占位/不可用(如返回 "Hello, world!" 或 Not Found)时,
    自动回退 NIM —— 替换可逆, 研究链路永不因 opencode 断链。
    """
    from obase.provider_registry import ProviderRegistry

    key = _api_key()
    if not key:
        logger.warning(
            "OpenCode LLM 未注册: 未设置 OPENCODE_API_KEY(research 回落 NIM/default)"
        )
        return
    caller = _make_opencode_caller(
        key,
        base_url=os.getenv("OPENCODE_BASE_URL", DEFAULT_BASE_URL),
        model=os.getenv("OPENCODE_MODEL", DEFAULT_MODEL),
        timeout=float(os.getenv("OPENCODE_TIMEOUT_S", "600")),
    )
    # opencode 失败(端点不可用/HTTP/非 JSON)→ 自动回退 NIM(若已注册)。
    try:
        nim = ProviderRegistry.get().llm("nim")
        caller = _with_fallback(caller, nim, model=os.getenv("OPENCODE_MODEL", DEFAULT_MODEL))
    except Exception:
        pass
    ProviderRegistry.register("llm", "opencode", caller, replace=True)
    logger.info(
        "OpenCode LLM registered: %s @ %s (fallback=nim 就绪)",
        os.getenv("OPENCODE_MODEL", DEFAULT_MODEL),
        os.getenv("OPENCODE_BASE_URL", DEFAULT_BASE_URL),
    )


def _with_fallback(primary: Any, fallback: Any, *, model: str) -> Any:
    """包装 caller: 主调用失败自动回退 fallback。"""

    async def _wrapped(**kwargs: Any) -> dict[str, Any]:
        try:
            result: Any = await primary(**kwargs)
            return result if isinstance(result, dict) else {"content": str(result)}
        except Exception as exc:
            logger.warning("OpenCode(%s) 调用失败, 回退 NIM: %s", model, exc)
            fallback_result: Any = await fallback(**kwargs)
            if isinstance(fallback_result, dict):
                return fallback_result
            return {"content": str(fallback_result)}

    return _wrapped


__all__ = ["register_opencode_llm"]
