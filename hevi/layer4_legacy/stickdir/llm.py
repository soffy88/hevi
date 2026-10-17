"""免费 LLM 客户端 —— 本机 ollama, 纯 CPU, 超时/失败即回退。

不调用任何付费 API。默认打 ``127.0.0.1:11434`` 的 ``xiaoya-qwen3-4b-v2:latest``;
不可用或超时返回 ``None``, 调用方走确定性 fallback(两条路径共用同一套
schema + 白名单 + 无编造校验)。
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.environ.get(
    "STICKDIR_OLLAMA_BASE", os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
)
OLLAMA_MODEL = os.environ.get("STICKDIR_OLLAMA_MODEL", "xiaoya-qwen3-4b-v2:latest")
DEFAULT_TIMEOUT = float(os.environ.get("STICKDIR_LLM_TIMEOUT", "60"))


def probe(timeout: float = 4.0) -> bool:
    """ollama 是否在线(有该模型)。"""
    try:
        import httpx

        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=timeout)
        r.raise_for_status()
        names = {m["name"] for m in r.json().get("models", [])}
        return OLLAMA_MODEL in names
    except Exception:  # noqa: BLE001 - 探测失败即视为不可用
        return False


def complete(prompt: str, *, timeout: float | None = None, model: str | None = None) -> str | None:
    """单轮补全;失败返回 ``None``(调用方回退)。"""
    payload = {
        "model": model or OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.4, "num_predict": 900},
    }
    try:
        import httpx

        r = httpx.post(
            f"{OLLAMA_BASE}/api/generate",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=timeout or DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        text = r.json().get("response", "")
        return text or None
    except Exception as exc:  # noqa: BLE001 - 网络/超时/解析失败都回退
        logger.warning("ollama complete failed: %s", exc)
        return None


def make_completer(*, timeout: float | None = None) -> callable | None:
    """若 ollama 可用, 返回一个 ``complete`` 闭包;否则 ``None``。"""
    if not probe():
        logger.info("ollama not available at %s; using deterministic fallback", OLLAMA_BASE)
        return None

    def _c(prompt: str) -> str:
        out = complete(prompt, timeout=timeout)
        if out is None:
            raise RuntimeError("ollama returned no content")
        return out

    return _c


__all__ = ["DEFAULT_TIMEOUT", "OLLAMA_BASE", "OLLAMA_MODEL", "complete", "make_completer", "probe"]
