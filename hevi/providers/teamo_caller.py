"""TeamoRouter LLM(OpenAI 兼容):Grok / Pi / 福利版 DeepSeek。

用户提供的聚合网关,chat/completions 协议。凭证走环境变量,不进仓库:

    TEAMOROUTER_BASE_URL   默认 https://api.teamorouter.com/v1
    TEAMOROUTER_API_KEY    sk-teamo-...
    TEAMOROUTER_GROK_MODEL 默认 grok-4.6(目录实测 id)
    TEAMOROUTER_PI_MODEL    默认 pi(目录暂无此 id,可改)
    TEAMOROUTER_FREE_MODEL  默认 deepseek-v4-flash-free
    TEAMOROUTER_TIMEOUT_S   默认 300

注册:
    llm/grok        Grok
    llm/pi          Pi
    llm/teamo       默认走 Grok,调用方可传 model=
    llm/teamo_free  网关标价免费的 DeepSeek 福利版

HEVI_LLM_PROVIDER=grok|pi|teamo|teamo_free 时覆盖 llm/default。
无 key 时静默跳过。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.teamorouter.com/v1"
DEFAULT_GROK_MODEL = "grok-4.6"
DEFAULT_PI_MODEL = "pi"
DEFAULT_FREE_MODEL = "deepseek-v4-flash-free"
DEFAULT_TIMEOUT = 300.0

_SLOT_ENV = {
    "grok": "TEAMOROUTER_GROK_MODEL",
    "pi": "TEAMOROUTER_PI_MODEL",
    "teamo_free": "TEAMOROUTER_FREE_MODEL",
    "teamo": "TEAMOROUTER_GROK_MODEL",
}
_SLOT_DEFAULT = {
    "grok": DEFAULT_GROK_MODEL,
    "pi": DEFAULT_PI_MODEL,
    "teamo_free": DEFAULT_FREE_MODEL,
    "teamo": DEFAULT_GROK_MODEL,
}


def _env_file_values() -> dict[str, str]:
    """进程环境没有 compose 注入时,读 /app/.env 或仓库 .env。"""
    found: dict[str, str] = {}
    for candidate in (Path("/app/.env"), Path(".env")):
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            found[key.strip()] = value.strip().strip('"').strip("'")
    return found


def _lookup(name: str, default: str = "") -> str:
    raw = os.getenv(name, "").strip()
    if raw:
        return raw
    return _env_file_values().get(name, default).strip()


def _api_key() -> str:
    return _lookup("TEAMOROUTER_API_KEY")


def _base_url() -> str:
    return (_lookup("TEAMOROUTER_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")


def _timeout() -> float:
    raw = _lookup("TEAMOROUTER_TIMEOUT_S", str(DEFAULT_TIMEOUT))
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT


def slot_model(slot: str) -> str:
    env = _SLOT_ENV.get(slot, "TEAMOROUTER_GROK_MODEL")
    fallback = _SLOT_DEFAULT.get(slot, DEFAULT_GROK_MODEL)
    return _lookup(env, fallback) or fallback


def _messages_from_kwargs(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    messages = list(kwargs.get("messages") or [])
    system = kwargs.get("system")
    if system:
        messages = [{"role": "system", "content": str(system)}, *messages]
    if not messages:
        raise RuntimeError("TeamoRouter 调用缺 messages")
    return messages


def teamo_chat_completions(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 4096,
    temperature: float | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """同步打 OpenAI 兼容 /chat/completions,返回 DashScope 形状 + content。"""
    key = (api_key if api_key is not None else _api_key()).strip()
    if not key:
        raise RuntimeError("TEAMOROUTER_API_KEY 未设置")
    url = f"{(base_url or _base_url()).rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    with httpx.Client(trust_env=True, timeout=timeout or _timeout()) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"TeamoRouter HTTP {response.status_code} model={model}: {response.text[:300]}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"TeamoRouter 返回非 JSON({response.text[:80]!r}); "
            f"检查 TEAMOROUTER_BASE_URL={base_url or _base_url()}"
        ) from exc
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"TeamoRouter 响应缺 choices: {str(data)[:200]}")
    message = choices[0].get("message") or {}
    text = message.get("content") or message.get("reasoning") or ""
    if not text:
        raise RuntimeError(f"TeamoRouter 返回空 content model={model}")
    try:
        from hevi.providers.registry import _coerce_llm_json_text

        text = _coerce_llm_json_text(str(text))
    except Exception:
        text = str(text)
    native_choices = [
        {"message": c.get("message", {}), "finish_reason": c.get("finish_reason", "")}
        for c in choices
    ]
    return {
        "output": {"choices": native_choices},
        "usage": data.get("usage", {}),
        "content": text,
        "model": data.get("model") or model,
        "provider": "teamo",
    }


def _make_adapter(slot: str) -> type:
    locked = slot != "teamo"

    class _TeamoAdapter:
        def __init__(self, **kwargs: Any):
            kwargs.pop("result_format", None)
            model = str(kwargs.get("model") or slot_model(slot)) if not locked else slot_model(slot)
            resp = teamo_chat_completions(
                model=model,
                messages=_messages_from_kwargs(kwargs),
                max_tokens=int(kwargs.get("max_tokens") or 4096),
                temperature=kwargs.get("temperature"),
            )
            self._resp = resp

        def __await__(self) -> Any:
            async def _dummy() -> dict[str, Any]:
                return self._resp

            return _dummy().__await__()

        def get(self, key: str, default: Any = None) -> Any:
            return self._resp.get(key, default)

    _TeamoAdapter.__name__ = f"Teamo{slot.title().replace('_', '')}Adapter"
    return _TeamoAdapter


def register_teamo_llm() -> None:
    """注册 grok/pi/teamo/teamo_free。无 key 静默跳过。"""
    from obase.provider_registry import ProviderRegistry

    if not _api_key():
        logger.warning("TeamoRouter LLM 未注册: 未设置 TEAMOROUTER_API_KEY")
        return
    for slot in ("grok", "pi", "teamo", "teamo_free"):
        ProviderRegistry.register("llm", slot, _make_adapter(slot), replace=True)
    preferred = os.getenv("HEVI_LLM_PROVIDER", "").strip().lower()
    if preferred in _SLOT_ENV:
        ProviderRegistry.register("llm", "default", _make_adapter(preferred), replace=True)
        logger.info(
            "LLM default → TeamoRouter %s (%s @ %s)",
            preferred,
            slot_model(preferred),
            _base_url(),
        )
    logger.info(
        "TeamoRouter LLM registered: grok=%s pi=%s free=%s @ %s",
        slot_model("grok"),
        slot_model("pi"),
        slot_model("teamo_free"),
        _base_url(),
    )


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_FREE_MODEL",
    "DEFAULT_GROK_MODEL",
    "DEFAULT_PI_MODEL",
    "register_teamo_llm",
    "slot_model",
    "teamo_chat_completions",
]
