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

from hevi.providers.reliability import (
    ProviderExecutionWrapper,
    RateLimitPolicy,
    ReliabilityConfig,
    TimeoutPolicy,
)


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
    timeout_s: float = 60.0

    def __post_init__(self) -> None:
        timeout_s = min(max(float(self.timeout_s), 1.0), 60.0)
        self.timeout_s = timeout_s
        self._wrapper = ProviderExecutionWrapper(
            "longcat",
            os.getenv("LONGCAT_MODEL", "LongCat-2.0"),
            config=ReliabilityConfig(
                timeout=TimeoutPolicy(
                    connect_s=min(5.0, timeout_s),
                    read_s=timeout_s,
                    write_s=min(10.0, timeout_s),
                    pool_s=min(5.0, timeout_s),
                    total_s=timeout_s,
                ),
                max_concurrency=4,
                rate_limit=RateLimitPolicy(requests_per_minute=60.0, burst=4),
            ),
        )

    async def __call__(self, **payload: Any) -> dict[str, Any]:
        body = dict(payload)
        body.setdefault("model", os.getenv("LONGCAT_MODEL", "LongCat-2.0"))
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        result = await self._wrapper.request_json(
            "POST",
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json_body=body,
            idempotent=True,
            output_token_budget=int(body.get("max_tokens") or 0),
        )
        return result.require_value()

    async def stream(self, **payload: Any) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE chunks after a bounded, non-retried wrapper execution.

        A partially consumed stream cannot be safely replayed, so this path
        opts out of retry while retaining the wrapper's timeout, circuit,
        bulkhead, rate-limit, budget, and metrics contract.
        """

        body = dict(payload)
        body.setdefault("model", os.getenv("LONGCAT_MODEL", "LongCat-2.0"))
        body["stream"] = True
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async def _collect() -> dict[str, Any]:
            chunks: list[dict[str, Any]] = []
            usage: dict[str, Any] = {}
            async with httpx.AsyncClient(
                timeout=self._wrapper.config.timeout.httpx_timeout
            ) as client, client.stream(
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
                        chunks.append(chunk)
                        if isinstance(chunk.get("usage"), dict):
                            usage = chunk["usage"]
            if not chunks:
                raise ValueError("LongCat stream contained no valid chunks")
            return {"chunks": chunks, "usage": usage}

        result = await self._wrapper.execute(
            _collect,
            idempotent=False,
            output_token_budget=int(body.get("max_tokens") or 0),
        )
        data = result.require_value()
        for chunk in data["chunks"]:
            yield chunk


def build_longcat_caller() -> LongCatProvider | None:
    base_url = _base_url()
    if not base_url:
        return None
    return LongCatProvider(
        base_url=base_url,
        api_key=os.getenv("LONGCAT_API_KEY", "").strip(),
        timeout_s=float(os.getenv("LONGCAT_TIMEOUT_S", "60")),
    )


__all__ = ["LongCatProvider", "build_longcat_caller", "longcat_provider_status"]
